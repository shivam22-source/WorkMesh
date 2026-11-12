"""Live PostgreSQL 16 tests for Phase 5 Step 2.

Runs against the real PostgreSQL 16 container (ekr-postgres / test_knowledge).
Verifies:
1. Lease acquisition, renewal, expiry, and stale-worker fencing.
2. Transaction rollback and atomic batch persistence.
3. Relationship metadata immutability and conflict rejection.
4. Defensive JSONB backfill handling for non-array/malformed JSON types.
5. Scoped document/chunk and ACL replacement.
6. Relationship ownership and graph authorization queries.
7. Document and chunk column mapping regression (author, source_type, url, token_count).
"""

from datetime import datetime, timezone

import psycopg
import pytest

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.repository import (
    FencedSyncError,
    PostgresKnowledgeRepository,
)
from app.normalization.models import CanonicalDocument


def detect_live_postgres_url() -> str:
    from app.common.config import get_settings
    settings = get_settings()
    custom_test_url = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}@"
        f"{settings.postgres_host}:{settings.postgres_port}/test_knowledge"
    )
    candidates = [
        custom_test_url,
        "postgresql://knowledge:local_dev_only_change_me@localhost:5432/test_knowledge",
        "postgresql://knowledge:local_dev_only_change_me@127.0.0.1:5432/test_knowledge",
    ]
    for url in candidates:
        try:
            with psycopg.connect(url, connect_timeout=1) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    return url
        except Exception:
            continue
    return None


LIVE_POSTGRES_URL = detect_live_postgres_url()


@pytest.fixture(autouse=True)
def clean_test_database():
    if not LIVE_POSTGRES_URL:
        pytest.skip("Live PostgreSQL 16 container not reachable")
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                TRUNCATE TABLE 
                    source_records, 
                    documents, 
                    chunks, 
                    acl_references, 
                    entities, 
                    relationships, 
                    relationship_owners, 
                    sync_state 
                CASCADE;
            """)
        conn.commit()
    yield


# -----------------------------------------------------------------------------
# 1. Lease Acquisition, Expiry, and Stale-Worker Fencing
# -----------------------------------------------------------------------------

def test_live_postgres_lease_acquisition_expiry_and_stale_worker_fencing():
    """Verify lease lifecycle, expiry, and fence-out in PostgreSQL 16."""
    repo = PostgresKnowledgeRepository(LIVE_POSTGRES_URL)

    # Worker 1 claims lease
    res1 = repo.claim_sync("GITHUB", lease_token="tok1", lease_ttl_seconds=5)
    assert res1 is not None
    assert res1.lease_token == "tok1"

    # Worker 2 attempts claim while unexpired -> fails (returns None)
    res2 = repo.claim_sync("GITHUB", lease_token="tok2", lease_ttl_seconds=5)
    assert res2 is None

    # Worker 1 renews lease
    renewed = repo.renew_lease("GITHUB", lease_token="tok1", lease_ttl_seconds=10)
    assert renewed is True

    # Bad token cannot renew
    renew_bad = repo.renew_lease("GITHUB", lease_token="wrong_tok", lease_ttl_seconds=10)
    assert renew_bad is False

    # Force lease expiration directly in PostgreSQL
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sync_state 
                SET metadata = jsonb_set(
                    metadata, 
                    '{lease_expires_at}', 
                    to_jsonb(to_char(clock_timestamp() - interval '10 seconds', 'YYYY-MM-DD"T"HH24:MI:SS.USOF'))
                )
                WHERE source_type = 'GITHUB';
            """)
        conn.commit()

    # Now Worker 2 claims expired lease -> succeeds
    res3 = repo.claim_sync("GITHUB", lease_token="tok2", lease_ttl_seconds=5)
    assert res3 is not None
    assert res3.lease_token == "tok2"

    # Stale Worker 1 is fenced out of persist_sync_batch
    item = RawSourceItem(
        id="sr-1", source_type=SourceType.GITHUB, source_id="1", source_url="https://gh/1",
        title="PR", raw_content="text", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(FencedSyncError, match="Worker fenced out"):
        repo.persist_sync_batch("GITHUB", lease_token="tok1", next_cursor="c1", items=[item], docs=[], chunks=[], acls=[], entities=[], relationships=[])

    # Stale Worker 1 is fenced out of complete_sync
    with pytest.raises(FencedSyncError, match="Worker fenced out"):
        repo.complete_sync("GITHUB", lease_token="tok1")


# -----------------------------------------------------------------------------
# 2. Transaction Rollback, Atomic Persistence, and Column Mapping Regression
# -----------------------------------------------------------------------------

def test_live_postgres_transaction_rollback_and_atomic_batch_persistence():
    """Verify document/chunk columns, atomic commit, and complete rollback on failure in PostgreSQL 16."""
    repo = PostgresKnowledgeRepository(LIVE_POSTGRES_URL)
    repo.claim_sync("GITHUB", lease_token="tok-tx", lease_ttl_seconds=60)

    # Batch 1: valid items, documents, chunks, acls, and entities
    item1 = RawSourceItem(
        id="sr-b1", source_type=SourceType.GITHUB, source_id="1", source_url="https://gh/1",
        title="PR 1", raw_content="Content 1", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    doc1 = CanonicalDocument(
        id="doc-b1", source_record_id="sr-b1", source_type="GITHUB",
        title="Doc 1", content="Text 1", author="alice_engineer", url="https://gh/1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    chunk1 = CanonicalChunk(
        id="c-b1", document_id="doc-b1", chunk_index=0, content="Chunk 1", token_count=42,
        content_hash=CanonicalChunk.compute_hash("Chunk 1"),
    )
    acl1 = AclReference(
        resource_type="SOURCE_RECORD", resource_id="sr-b1", principal_type=PrincipalType.USER,
        principal_id="alice", permission="READ",
    )
    ent_ticket = Entity(id="ticket:T-1", entity_type=EntityType.TICKET.value, name="T-1")
    ent_pr = Entity(id="pr:company/repo:100", entity_type=EntityType.PULL_REQUEST.value, name="PR 100", source_record_id="sr-b1")
    rel1 = Relationship(
        source_entity_id="ticket:T-1", target_entity_id="pr:company/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"source_record_id": "sr-b1", "repository": "company/repo", "pr_number": "100", "ticket_id": "T-1"},
    )

    repo.persist_sync_batch(
        source_type="GITHUB", lease_token="tok-tx", next_cursor="cursor-1",
        items=[item1], docs=[doc1], chunks=[chunk1], acls=[acl1],
        entities=[ent_ticket, ent_pr], relationships=[rel1],
    )

    # Verify Batch 1 columns and values directly in PostgreSQL 16
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, cursor_value FROM sync_state WHERE source_type = 'GITHUB';")
            row = cur.fetchone()
            assert row[0] == "SYNCING"
            assert row[1] == "cursor-1"

            # Check document columns: author, source_type, url
            cur.execute("SELECT author, source_type, url, title FROM documents WHERE id = 'doc-b1';")
            d_row = cur.fetchone()
            assert d_row[0] == "alice_engineer"
            assert d_row[1] == "GITHUB"
            assert d_row[2] == "https://gh/1"
            assert d_row[3] == "Doc 1"

            # Check chunk token_count
            cur.execute("SELECT token_count, content FROM chunks WHERE id = 'c-b1';")
            c_row = cur.fetchone()
            assert c_row[0] == 42
            assert c_row[1] == "Chunk 1"

            # Check ACL and relationship owners in the same batch
            cur.execute("SELECT principal_id, permission FROM acl_references WHERE resource_id = 'sr-b1';")
            acl_row = cur.fetchone()
            assert acl_row[0] == "alice"
            assert acl_row[1] == "READ"

            cur.execute("SELECT source_record_id FROM relationship_owners WHERE source_record_id = 'sr-b1';")
            assert cur.fetchone()[0] == "sr-b1"

    # Batch 2: contains conflicting relationship metadata which triggers rollback
    item2 = RawSourceItem(
        id="sr-b2", source_type=SourceType.GITHUB, source_id="2", source_url="https://gh/2",
        title="PR 2", raw_content="Content 2", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    doc2 = CanonicalDocument(
        id="doc-b2", source_record_id="sr-b2", source_type="GITHUB",
        title="Doc 2", content="Text 2", author="bob", url="https://gh/2",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    bad_rel = Relationship(
        source_entity_id="ticket:T-1", target_entity_id="pr:company/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"repository": "wrong_repo", "pr_number": "100", "ticket_id": "T-1"},
    )

    with pytest.raises(ValueError, match="Metadata conflict"):
        repo.persist_sync_batch(
            source_type="GITHUB", lease_token="tok-tx", next_cursor="cursor-2",
            items=[item2], docs=[doc2], chunks=[], acls=[], entities=[], relationships=[bad_rel],
        )

    # Verify rollback: Batch 2 records do NOT exist in PostgreSQL, cursor remains "cursor-1"
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cursor_value, status FROM sync_state WHERE source_type = 'GITHUB';")
            row = cur.fetchone()
            assert row[0] == "cursor-1"
            assert row[1] == "SYNCING"

            cur.execute("SELECT count(*) FROM source_records WHERE id = 'sr-b2';")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM documents WHERE id = 'doc-b2';")
            assert cur.fetchone()[0] == 0

    # Mark failed
    repo.fail_sync("GITHUB", lease_token="tok-tx", error_message="Batch 2 failed")
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status, cursor_value FROM sync_state WHERE source_type = 'GITHUB';")
            row = cur.fetchone()
            assert row[0] == "FAILED"
            assert row[1] == "cursor-1"


# -----------------------------------------------------------------------------
# 3. Relationship Metadata Immutability and Conflict Rejection
# -----------------------------------------------------------------------------

def test_live_postgres_relationship_metadata_immutability_and_conflict_rejection():
    """Verify that stored relationship metadata in PostgreSQL cannot be mutated by subsequent writes."""
    repo = PostgresKnowledgeRepository(LIVE_POSTGRES_URL)
    repo.claim_sync("GITHUB", lease_token="tok-immut", lease_ttl_seconds=60)

    item = RawSourceItem(
        id="sr-pr", source_type=SourceType.GITHUB, source_id="1", source_url="https://gh/1",
        title="PR 1", raw_content="PR", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    ent_t = Entity(id="ticket:T-1", entity_type=EntityType.TICKET.value, name="T-1")
    ent_p = Entity(id="pr:org/repo:100", entity_type=EntityType.PULL_REQUEST.value, name="PR 100", source_record_id="sr-pr")

    rel = Relationship(
        source_entity_id="ticket:T-1", target_entity_id="pr:org/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"source_record_id": "sr-pr", "repository": "org/repo", "pr_number": "100", "ticket_id": "T-1"},
    )

    repo.persist_sync_batch(
        source_type="GITHUB", lease_token="tok-immut", next_cursor="c1",
        items=[item], docs=[], chunks=[], acls=[], entities=[ent_t, ent_p], relationships=[rel],
    )

    # Verify stored metadata in Postgres
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT metadata FROM relationships 
                WHERE source_entity_id = 'ticket:T-1' AND target_entity_id = 'pr:org/repo:100';
            """)
            meta = cur.fetchone()[0]
            assert meta["repository"] == "org/repo"
            assert meta["pr_number"] == "100"

            cur.execute("SELECT count(*) FROM relationship_owners WHERE source_record_id = 'sr-pr';")
            assert cur.fetchone()[0] == 1

    # Attempt to write conflicting metadata in subsequent batch
    item2 = RawSourceItem(
        id="sr-ticket", source_type=SourceType.GITHUB, source_id="2", source_url="https://gh/2",
        title="PR 2", raw_content="PR", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    conflicting_rel = Relationship(
        source_entity_id="ticket:T-1", target_entity_id="pr:org/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"source_record_id": "sr-ticket", "repository": "different/repo", "pr_number": "100", "ticket_id": "T-1"},
    )

    with pytest.raises(ValueError, match="Metadata conflict"):
        repo.persist_sync_batch(
            source_type="GITHUB", lease_token="tok-immut", next_cursor="c2",
            items=[item2], docs=[], chunks=[], acls=[], entities=[], relationships=[conflicting_rel],
        )

    # Verify metadata in PostgreSQL was NOT mutated
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT metadata FROM relationships 
                WHERE source_entity_id = 'ticket:T-1' AND target_entity_id = 'pr:org/repo:100';
            """)
            meta = cur.fetchone()[0]
            assert meta["repository"] == "org/repo"
            assert meta["pr_number"] == "100"


# -----------------------------------------------------------------------------
# 4. JSONB Backfill Handling for Different JSON Types
# -----------------------------------------------------------------------------

def test_live_postgres_jsonb_backfill_handling_for_different_json_types():
    """Verify defensive handling of strings, objects, integers, and arrays in V002 backfill queries."""
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            # 1. Insert source records first (satisfies foreign key constraints for entities)
            cur.execute("""
                INSERT INTO source_records (id, source_type, source_id, source_url, title, raw_content, metadata)
                VALUES 
                    ('sr-pr-1', 'GITHUB', '1', 'https://gh/1', 'PR 1', 'PR content', '{"ticket_ids": "FEAT-1"}'::jsonb),
                    ('sr-c1', 'GITHUB', 'c1', 'https://gh/c1', 'C1', 'Content', '{"author": "alice"}'::jsonb);
            """)

            # 2. Insert entities and relationships
            cur.execute("""
                INSERT INTO entities (id, entity_type, name, source_record_id, metadata)
                VALUES 
                    ('ticket:FEAT-1', 'TICKET', 'FEAT-1', NULL, '{"ticket_id": "FEAT-1"}'::jsonb),
                    ('pr:org/repo:1', 'PULL_REQUEST', 'PR 1', 'sr-pr-1', '{"repository": "org/repo", "number": "1"}'::jsonb),
                    ('commit:org/repo:c1', 'COMMIT', 'Commit 1', 'sr-c1', '{"repository": "org/repo", "sha": "c1"}'::jsonb),
                    ('employee:alice', 'EMPLOYEE', 'Alice', NULL, '{"login": "alice"}'::jsonb);

                INSERT INTO relationships (id, source_entity_id, target_entity_id, relationship_type, metadata)
                VALUES 
                    (1, 'ticket:FEAT-1', 'pr:org/repo:1', 'implemented_by', '{"repository": "org/repo", "pr_number": "1"}'::jsonb),
                    (2, 'pr:org/repo:1', 'commit:org/repo:c1', 'contains', '{"repository": "org/repo", "sha": "c1"}'::jsonb),
                    (3, 'commit:org/repo:c1', 'employee:alice', 'authored_by', '{"repository": "org/repo", "sha": "c1"}'::jsonb);
            """)

            # 3. Path 1: String ticket_ids (malformed) -> does NOT match, no error
            cur.execute("""
                INSERT INTO relationship_owners (relationship_id, source_record_id)
                SELECT r.id, t.source_record_id
                FROM relationships r
                JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'TICKET'
                JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'PULL_REQUEST'
                JOIN source_records sr ON t.source_record_id = sr.id AND sr.source_type = 'GITHUB'
                WHERE r.relationship_type = 'implemented_by'
                  AND t.source_record_id IS NOT NULL
                  AND (
                      (sr.metadata ? 'ticket_ids' AND jsonb_typeof(sr.metadata->'ticket_ids') = 'array' AND sr.metadata->'ticket_ids' @> to_jsonb(s.name))
                      OR (sr.raw_content ~* ('\\m' || s.name || '\\M') OR sr.title ~* ('\\m' || s.name || '\\M'))
                  )
                ON CONFLICT DO NOTHING;
            """)
            assert cur.rowcount == 0  # Safely rejected string

            # Now update to valid array
            cur.execute("UPDATE source_records SET metadata = '{\"ticket_ids\": [\"FEAT-1\"]}'::jsonb WHERE id = 'sr-pr-1';")
            cur.execute("""
                INSERT INTO relationship_owners (relationship_id, source_record_id)
                SELECT r.id, t.source_record_id
                FROM relationships r
                JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'TICKET'
                JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'PULL_REQUEST'
                JOIN source_records sr ON t.source_record_id = sr.id AND sr.source_type = 'GITHUB'
                WHERE r.relationship_type = 'implemented_by'
                  AND t.source_record_id IS NOT NULL
                  AND (
                      (sr.metadata ? 'ticket_ids' AND jsonb_typeof(sr.metadata->'ticket_ids') = 'array' AND sr.metadata->'ticket_ids' @> to_jsonb(s.name))
                      OR (sr.raw_content ~* ('\\m' || s.name || '\\M') OR sr.title ~* ('\\m' || s.name || '\\M'))
                  )
                ON CONFLICT DO NOTHING;
            """)
            assert cur.rowcount == 1  # Successfully matched array!

            # 4. Path 4a: Non-array commits -> CASE expression produces empty array without error
            cur.execute("UPDATE source_records SET metadata = '{\"commits\": \"c1\"}'::jsonb WHERE id = 'sr-pr-1';")
            cur.execute("""
                INSERT INTO relationship_owners (relationship_id, source_record_id)
                SELECT r.id, s_sr.id
                FROM relationships r
                JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'PULL_REQUEST'
                JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'COMMIT'
                JOIN source_records s_sr ON s.source_record_id = s_sr.id AND s_sr.source_type = 'GITHUB'
                WHERE r.relationship_type = 'contains'
                  AND s_sr.metadata IS NOT NULL
                  AND s_sr.metadata ? 'commits'
                  AND EXISTS (
                      SELECT 1 
                      FROM jsonb_array_elements(
                          CASE 
                              WHEN jsonb_typeof(s_sr.metadata->'commits') = 'array' 
                              THEN s_sr.metadata->'commits' 
                              ELSE '[]'::jsonb 
                          END
                      ) c
                      WHERE (
                          (jsonb_typeof(c) = 'object' AND c->>'sha' IS NOT NULL AND c->>'sha' = t.metadata->>'sha')
                          OR (jsonb_typeof(c) = 'string' AND c#>>'{}' = t.metadata->>'sha')
                      )
                  )
                ON CONFLICT DO NOTHING;
            """)
            assert cur.rowcount == 0  # No crash, no match

            # Update to mixed array elements
            cur.execute("UPDATE source_records SET metadata = '{\"commits\": [123, null, {}, {\"sha\": \"c1\"}]}'::jsonb WHERE id = 'sr-pr-1';")
            cur.execute("""
                INSERT INTO relationship_owners (relationship_id, source_record_id)
                SELECT r.id, s_sr.id
                FROM relationships r
                JOIN entities s ON r.source_entity_id = s.id AND s.entity_type = 'PULL_REQUEST'
                JOIN entities t ON r.target_entity_id = t.id AND t.entity_type = 'COMMIT'
                JOIN source_records s_sr ON s.source_record_id = s_sr.id AND s_sr.source_type = 'GITHUB'
                WHERE r.relationship_type = 'contains'
                  AND s_sr.metadata IS NOT NULL
                  AND s_sr.metadata ? 'commits'
                  AND EXISTS (
                      SELECT 1 
                      FROM jsonb_array_elements(
                          CASE 
                              WHEN jsonb_typeof(s_sr.metadata->'commits') = 'array' 
                              THEN s_sr.metadata->'commits' 
                              ELSE '[]'::jsonb 
                          END
                      ) c
                      WHERE (
                          (jsonb_typeof(c) = 'object' AND c->>'sha' IS NOT NULL AND c->>'sha' = t.metadata->>'sha')
                          OR (jsonb_typeof(c) = 'string' AND c#>>'{}' = t.metadata->>'sha')
                      )
                  )
                ON CONFLICT DO NOTHING;
            """)
            assert cur.rowcount == 1  # Successfully matched object sha!
        conn.commit()


# -----------------------------------------------------------------------------
# 5. Scoped Document/Chunk and ACL Replacement
# -----------------------------------------------------------------------------

def test_live_postgres_scoped_document_chunk_and_acl_replacement():
    """Verify chunk pruning on shrink, zero-doc cleanup, and ACL replacement in PostgreSQL 16."""
    repo = PostgresKnowledgeRepository(LIVE_POSTGRES_URL)
    repo.claim_sync("GITHUB", lease_token="tok-scope", lease_ttl_seconds=60)

    item = RawSourceItem(
        id="sr-scope", source_type=SourceType.GITHUB, source_id="1", source_url="https://gh/1",
        title="PR 1", raw_content="Large", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    doc = CanonicalDocument(
        id="doc-scope", source_record_id="sr-scope", source_type="GITHUB",
        title="Doc 1", content="Large content", author="alice", url="https://gh/1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    c0 = CanonicalChunk(id="c0", document_id="doc-scope", chunk_index=0, content="part 0", token_count=2, content_hash=CanonicalChunk.compute_hash("part 0"))
    c1 = CanonicalChunk(id="c1", document_id="doc-scope", chunk_index=1, content="part 1", token_count=2, content_hash=CanonicalChunk.compute_hash("part 1"))
    c2 = CanonicalChunk(id="c2", document_id="doc-scope", chunk_index=2, content="part 2", token_count=2, content_hash=CanonicalChunk.compute_hash("part 2"))

    acl1 = AclReference(resource_type="SOURCE_RECORD", resource_id="sr-scope", principal_type=PrincipalType.USER, principal_id="user_alice", permission="READ")

    # Ingest 3 chunks and Alice ACL
    repo.persist_sync_batch(
        source_type="GITHUB", lease_token="tok-scope", next_cursor="c1",
        items=[item], docs=[doc], chunks=[c0, c1, c2], acls=[acl1], entities=[], relationships=[],
    )

    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks WHERE document_id = 'doc-scope';")
            assert cur.fetchone()[0] == 3
            cur.execute("SELECT count(*) FROM acl_references WHERE resource_id = 'sr-scope';")
            assert cur.fetchone()[0] == 1

    # Re-sync document shrunk to 1 chunk, ACL replaced with Bob
    c0_new = CanonicalChunk(id="c0_new", document_id="doc-scope", chunk_index=0, content="shrunk", token_count=1, content_hash=CanonicalChunk.compute_hash("shrunk"))
    acl2 = AclReference(resource_type="SOURCE_RECORD", resource_id="sr-scope", principal_type=PrincipalType.USER, principal_id="user_bob", permission="READ")

    repo.persist_sync_batch(
        source_type="GITHUB", lease_token="tok-scope", next_cursor="c2",
        items=[item], docs=[doc], chunks=[c0_new], acls=[acl2], entities=[], relationships=[],
    )

    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM chunks WHERE document_id = 'doc-scope';")
            rows = cur.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "c0_new"  # Stale c0, c1, c2 pruned!

            cur.execute("SELECT principal_id FROM acl_references WHERE resource_id = 'sr-scope';")
            rows = cur.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "user_bob"  # Alice ACL replaced!

    # Replay producing 0 documents: deletes document and chunks
    repo.persist_sync_batch(
        source_type="GITHUB", lease_token="tok-scope", next_cursor="c3",
        items=[item], docs=[], chunks=[], acls=[], entities=[], relationships=[],
    )

    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents WHERE id = 'doc-scope';")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM chunks WHERE document_id = 'doc-scope';")
            assert cur.fetchone()[0] == 0


# -----------------------------------------------------------------------------
# 6. Relationship Ownership and Authorization Queries
# -----------------------------------------------------------------------------

def test_live_postgres_relationship_ownership_and_authorization_queries():
    """Verify graph traversal security, unowned edge hiding, and neighbor redaction in PostgreSQL 16."""
    repo = PostgresKnowledgeRepository(LIVE_POSTGRES_URL)
    repo.claim_sync("GITHUB", lease_token="tok-graph", lease_ttl_seconds=60)

    # Public PR contains private commit
    item_pr = RawSourceItem(
        id="sr-pr-pub", source_type=SourceType.GITHUB, source_id="10", source_url="https://gh/pr/10",
        title="Public PR 10", raw_content="PR", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    item_commit = RawSourceItem(
        id="sr-commit-priv", source_type=SourceType.GITHUB, source_id="c10", source_url="https://gh/commit/c10",
        title="Private Commit", raw_content="Commit", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    ent_pr = Entity(id="pr:repo:10", entity_type=EntityType.PULL_REQUEST.value, name="PR 10", source_record_id="sr-pr-pub")
    ent_commit = Entity(
        id="commit:repo:c10", entity_type=EntityType.COMMIT.value, name="Commit 10",
        source_record_id="sr-commit-priv",
        metadata={"repository": "repo", "sha": "c10", "internal_secret_token": "confidential_xyz"},
    )
    rel = Relationship(
        source_entity_id="pr:repo:10", target_entity_id="commit:repo:c10",
        relationship_type=RelationshipType.CONTAINS.value,
        metadata={"source_record_id": "sr-pr-pub", "repository": "repo", "pr_number": "10", "sha": "c10"},
    )

    acl_pr = AclReference(resource_type="SOURCE_RECORD", resource_id="sr-pr-pub", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ")
    acl_commit = AclReference(resource_type="SOURCE_RECORD", resource_id="sr-commit-priv", principal_type=PrincipalType.USER, principal_id="admin_user", permission="READ")

    repo.persist_sync_batch(
        source_type="GITHUB", lease_token="tok-graph", next_cursor="c1",
        items=[item_pr, item_commit], docs=[], chunks=[], acls=[acl_pr, acl_commit],
        entities=[ent_pr, ent_commit], relationships=[rel],
    )

    # 1. Standard user traverses from public PR -> returns neighbor with redacted anchor
    results = repo.get_relationships_for_entity("pr:repo:10", direction="OUTGOING", user_id="standard_user")
    assert len(results) == 1
    rel_out, neighbor = results[0]
    assert neighbor.id == "commit:repo:c10"
    # Private anchor redacted to None!
    assert neighbor.source_record_id is None
    # Private metadata stripped!
    assert "internal_secret_token" not in neighbor.metadata
    assert neighbor.metadata.get("sha") == "c10"

    # 2. Unowned legacy edge with public endpoints is strictly hidden from traversal
    with psycopg.connect(LIVE_POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO entities (id, entity_type, name, source_record_id, metadata)
                VALUES 
                    ('pr:repo:99', 'PULL_REQUEST', 'PR 99', 'sr-pr-pub', '{"repository": "repo", "number": "99"}'::jsonb),
                    ('commit:repo:c99', 'COMMIT', 'Commit 99', 'sr-pr-pub', '{"repository": "repo", "sha": "c99"}'::jsonb);

                INSERT INTO relationships (id, source_entity_id, target_entity_id, relationship_type, metadata)
                VALUES (999, 'pr:repo:99', 'commit:repo:c99', 'contains', '{"repository": "repo", "pr_number": "99", "sha": "c99"}'::jsonb);
            """)
        conn.commit()

    # Traversal from pr:repo:99 must yield [] because relationship_id 999 has 0 rows in relationship_owners
    unowned_results = repo.get_relationships_for_entity("pr:repo:99", direction="OUTGOING", user_id="standard_user")
    assert unowned_results == []

    # 3. Unauthorized starting entity returns [] immediately
    ent_secret = Entity(id="pr:repo:classified", entity_type=EntityType.PULL_REQUEST.value, name="Classified PR", source_record_id="sr-commit-priv")
    repo.save_entities([ent_secret])
    unauthorized_start = repo.get_relationships_for_entity("pr:repo:classified", direction="OUTGOING", user_id="standard_user")
    assert unauthorized_start == []


@pytest.mark.skipif(LIVE_POSTGRES_URL is None, reason="Requires real PostgreSQL service")
def test_live_postgres_low_access_user_vector_search_and_no_leakage():
    """Verify in real PostgreSQL that low-access user (1% of seeded corpus) retrieves permitted chunks with no ACL leakage."""
    repo = PostgresKnowledgeRepository(LIVE_POSTGRES_URL)
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)

    raw_items = []
    docs = []
    chunks = []
    acls = []
    for i in range(100):
        sr_id = f"sr-1pct-{i:03d}"
        doc_id = f"doc-1pct-{i:03d}"
        chunk_id = f"chunk-1pct-{i:03d}"
        raw_items.append(
            RawSourceItem(
                id=sr_id,
                source_type=SourceType.GITHUB,
                source_id=doc_id,
                source_url=f"https://github.com/org/repo/pull/{i}",
                title=f"Doc {i}",
                raw_content=f"Vector ACL test content {i}",
                created_at=now,
                updated_at=now,
            )
        )
        docs.append(
            CanonicalDocument(
                id=doc_id,
                source_record_id=sr_id,
                source_type="GITHUB",
                title=f"Doc {i}",
                content=f"Vector ACL test content {i}",
                author="eng",
                url=f"https://github.com/org/repo/pull/{i}",
                created_at=now,
                updated_at=now,
            )
        )
        # Put non-target vectors slightly closer/varied and ensure unit norm
        vec = [0.05] * 384
        vec[0] = 0.2 if i == 99 else 0.05 + 0.0001 * i
        chunks.append(
            CanonicalChunk(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=0,
                content=f"Vector ACL test content {i}",
                token_count=5,
                content_hash=CanonicalChunk.compute_hash(f"Vector ACL test content {i}"),
                embedding=vec,
                created_at=now,
            )
        )
        if i == 99:
            acls.append(
                AclReference(
                    resource_type="DOCUMENT",
                    resource_id=doc_id,
                    principal_type=PrincipalType.USER,
                    principal_id="test_user_1",
                    permission="READ",
                )
            )
        else:
            acls.append(
                AclReference(
                    resource_type="DOCUMENT",
                    resource_id=doc_id,
                    principal_type=PrincipalType.GROUP,
                    principal_id="group_other_99pct",
                    permission="READ",
                )
            )

    repo.save_source_records(raw_items)
    repo.save_documents(docs)
    repo.save_chunks(chunks)
    repo.save_acls(acls)

    test_vector = [0.05] * 384
    results = repo.search_vector(test_vector, limit=5, user_id="test_user_1", group_ids=[])
    assert len(results) == 1
    assert results[0].document_id == "doc-1pct-099"

    # Completely unauthorized user gets zero results
    unauth_results = repo.search_vector(test_vector, limit=5, user_id="unauthorized_ghost_user", group_ids=[])
    assert len(unauth_results) == 0


@pytest.mark.skipif(LIVE_POSTGRES_URL is None, reason="Requires real PostgreSQL service")
def test_live_postgres_hnsw_settings_transaction_scoping():
    """Verify hnsw.ef_search and hnsw.iterative_scan are SET LOCAL inside transaction and revert without leak."""
    repo = PostgresKnowledgeRepository(LIVE_POSTGRES_URL)

    with repo._get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT '[1]'::vector;")
            cur.execute("SHOW hnsw.ef_search;")
            ef_initial = cur.fetchone()[0]
            cur.execute("SHOW hnsw.iterative_scan;")
            iter_initial = cur.fetchone()[0]

        # Commit initial check so connection is idle for the scoped transaction
        conn.commit()

        # Execute scoped transaction block as done in search_vector
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL hnsw.ef_search = 100;")
                cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
                cur.execute("SHOW hnsw.ef_search;")
                assert cur.fetchone()[0] == "100"
                cur.execute("SHOW hnsw.iterative_scan;")
                assert cur.fetchone()[0] == "relaxed_order"

        # Verify parameters immediately revert upon transaction exit on the same connection
        with conn.cursor() as cur:
            cur.execute("SHOW hnsw.ef_search;")
            ef_after = cur.fetchone()[0]
            cur.execute("SHOW hnsw.iterative_scan;")
            iter_after = cur.fetchone()[0]

        assert ef_after == ef_initial, f"hnsw.ef_search leaked! Expected {ef_initial}, got {ef_after}"
        assert iter_after == iter_initial, f"hnsw.iterative_scan leaked! Expected {iter_initial}, got {iter_after}"
