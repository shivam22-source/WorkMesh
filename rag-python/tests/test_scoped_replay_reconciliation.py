"""Tests for scoped replay reconciliation, immutable relationship metadata, and graph traversal authorization (Phase 5 Step 2)."""

from datetime import datetime, timezone
import pytest

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.repository import (
    InMemoryKnowledgeRepository,
    PostgresKnowledgeRepository,
    derive_canonical_metadata,
)
from app.normalization.models import CanonicalDocument


def test_existing_relationship_metadata_never_overwritten():
    """Verify that existing relationship metadata is never overwritten by subsequent saves."""
    repo = InMemoryKnowledgeRepository()

    rel1 = Relationship(
        source_entity_id="ticket:T-1",
        target_entity_id="pr:company/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"repository": "company/repo", "pr_number": "100", "ticket_id": "T-1"},
    )
    repo.save_relationships([rel1])

    # Re-save edge
    rel2 = Relationship(
        source_entity_id="ticket:T-1",
        target_entity_id="pr:company/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"repository": "company/repo", "pr_number": "100", "ticket_id": "T-1"},
    )
    repo.save_relationships([rel2])

    key = ("ticket:T-1", "pr:company/repo:100", RelationshipType.IMPLEMENTED_BY.value)
    stored = repo.relationships[key]
    assert stored.metadata["repository"] == "company/repo"
    assert stored.metadata["pr_number"] == "100"


def test_relationship_metadata_mismatch_raises_value_error():
    """Verify that incoming relationship metadata conflicting with canonical structural properties raises ValueError."""
    repo = InMemoryKnowledgeRepository()

    # Incoming pr_number 999 conflicts with endpoint pr:company/repo:100
    bad_rel = Relationship(
        source_entity_id="ticket:T-1",
        target_entity_id="pr:company/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"repository": "company/repo", "pr_number": "999", "ticket_id": "T-1"},
    )
    with pytest.raises(ValueError, match="Metadata conflict"):
        repo.save_relationships([bad_rel])


def test_relationship_metadata_derived_unambiguously_with_colons():
    """Repository names and IDs containing colons are parsed unambiguously using rsplit."""
    canonical = derive_canonical_metadata(
        source_entity_id="ticket:SEC-404",
        target_entity_id="pr:git.internal:8080/org/core-infra:42",
        rel_type="implemented_by",
    )
    assert canonical["repository"] == "git.internal:8080/org/core-infra"
    assert canonical["pr_number"] == "42"
    assert canonical["ticket_id"] == "SEC-404"

    # Commit relationship (contains)
    commit_meta = derive_canonical_metadata(
        source_entity_id="pr:git.internal:8080/org/core-infra:42",
        target_entity_id="commit:git.internal:8080/org/core-infra:deadbeef0123",
        rel_type="contains",
    )
    assert commit_meta["repository"] == "git.internal:8080/org/core-infra"
    assert commit_meta["pr_number"] == "42"
    assert commit_meta["sha"] == "deadbeef0123"

    # Authored by relationship
    author_meta = derive_canonical_metadata(
        source_entity_id="commit:git.internal:8080/org/core-infra:deadbeef0123",
        target_entity_id="employee:alice.dev",
        rel_type="authored_by",
    )
    assert author_meta["repository"] == "git.internal:8080/org/core-infra"
    assert author_meta["sha"] == "deadbeef0123"

    # Discussed in relationship
    slack_meta = derive_canonical_metadata(
        source_entity_id="ticket:PROJ:SUB:999",
        target_entity_id="slack:workspace:ops-channel:1700000000.123456",
        rel_type="discussed_in",
    )
    assert slack_meta["ticket_id"] == "PROJ:SUB:999"
    assert slack_meta["channel_id"] == "workspace:ops-channel"
    assert slack_meta["thread_ts"] == "1700000000.123456"


def test_persist_sync_batch_rejects_conflicting_relationship_metadata():
    """Verify that persist_sync_batch rejects relationships with metadata conflicting with endpoints."""
    repo = InMemoryKnowledgeRepository()
    repo.claim_sync("GITHUB", lease_token="tok-immut", lease_ttl_seconds=300)

    item = RawSourceItem(
        id="raw:gh:rel",
        source_type=SourceType.GITHUB,
        source_id="1",
        source_url="https://gh/1",
        title="PR 1",
        raw_content="PR",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    bad_rel = Relationship(
        source_entity_id="ticket:T-1",
        target_entity_id="pr:company/repo:100",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"repository": "wrong/repo", "pr_number": "100", "ticket_id": "T-1"},
    )

    with pytest.raises(ValueError, match="Metadata conflict"):
        repo.persist_sync_batch(
            source_type="GITHUB",
            lease_token="tok-immut",
            next_cursor="c1",
            items=[item],
            docs=[],
            chunks=[],
            acls=[],
            entities=[],
            relationships=[bad_rel],
        )


def test_source_record_producing_no_document_cleans_up_stale_documents_and_chunks():
    """Replaying a source record that produces zero documents cleans up previously indexed documents and chunks."""
    repo = InMemoryKnowledgeRepository()
    repo.claim_sync("EMAIL", lease_token="token-1", lease_ttl_seconds=300)

    item = RawSourceItem(
        id="raw:email:1",
        source_type=SourceType.EMAIL,
        source_id="msg-1",
        source_url="https://email/1",
        title="Msg 1",
        raw_content="Content",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    doc = CanonicalDocument(
        id="doc:email:1",
        source_record_id="raw:email:1",
        source_type=SourceType.EMAIL,
        title="Doc 1",
        content="Document content",
        url="https://email/1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    chunk = CanonicalChunk(
        id="chunk:email:1:0",
        document_id="doc:email:1",
        chunk_index=0,
        content="Chunk content",
        token_count=2,
        content_hash=CanonicalChunk.compute_hash("Chunk content"),
    )

    # Batch 1: normal ingestion produces 1 doc and 1 chunk
    repo.persist_sync_batch(
        source_type="EMAIL",
        lease_token="token-1",
        next_cursor="c1",
        items=[item],
        docs=[doc],
        chunks=[chunk],
        acls=[],
        entities=[],
        relationships=[],
    )
    assert "doc:email:1" in repo.documents
    assert "chunk:email:1:0" in repo.chunks

    # Batch 2: replay of raw:email:1 produces 0 documents
    repo.persist_sync_batch(
        source_type="EMAIL",
        lease_token="token-1",
        next_cursor="c1-replay",
        items=[item],
        docs=[],  # 0 docs produced
        chunks=[],
        acls=[],
        entities=[],
        relationships=[],
    )

    # Assert stale document and chunk were deleted
    assert "doc:email:1" not in repo.documents
    assert "chunk:email:1:0" not in repo.chunks


def test_stale_chunks_deleted_when_document_shrinks():
    """When a re-ingested document shrinks from 3 chunks to 1 chunk, stale chunks are deleted."""
    repo = InMemoryKnowledgeRepository()
    repo.claim_sync("GITHUB", lease_token="tok-1", lease_ttl_seconds=300)

    item = RawSourceItem(
        id="raw:gh:1",
        source_type=SourceType.GITHUB,
        source_id="1",
        source_url="https://gh/1",
        title="PR 1",
        raw_content="Content",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    doc = CanonicalDocument(
        id="doc:gh:1",
        source_record_id="raw:gh:1",
        source_type=SourceType.GITHUB,
        title="Doc 1",
        content="Initial large content",
        url="https://gh/1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    c0 = CanonicalChunk(id="c0", document_id="doc:gh:1", chunk_index=0, content="part 0", token_count=2, content_hash=CanonicalChunk.compute_hash("part 0"))
    c1 = CanonicalChunk(id="c1", document_id="doc:gh:1", chunk_index=1, content="part 1", token_count=2, content_hash=CanonicalChunk.compute_hash("part 1"))
    c2 = CanonicalChunk(id="c2", document_id="doc:gh:1", chunk_index=2, content="part 2", token_count=2, content_hash=CanonicalChunk.compute_hash("part 2"))

    # Initial batch: 3 chunks
    repo.persist_sync_batch(
        source_type="GITHUB",
        lease_token="tok-1",
        next_cursor="c1",
        items=[item],
        docs=[doc],
        chunks=[c0, c1, c2],
        acls=[],
        entities=[],
        relationships=[],
    )
    assert len([c for c in repo.chunks.values() if c.document_id == "doc:gh:1"]) == 3

    # Re-sync: document shrank to 1 chunk (c0_new)
    c0_new = CanonicalChunk(id="c0_new", document_id="doc:gh:1", chunk_index=0, content="shrunk part 0", token_count=3, content_hash=CanonicalChunk.compute_hash("shrunk part 0"))
    repo.persist_sync_batch(
        source_type="GITHUB",
        lease_token="tok-1",
        next_cursor="c2",
        items=[item],
        docs=[doc],
        chunks=[c0_new],
        acls=[],
        entities=[],
        relationships=[],
    )

    remaining_chunks = [c for c in repo.chunks.values() if c.document_id == "doc:gh:1"]
    assert len(remaining_chunks) == 1
    assert remaining_chunks[0].id == "c0_new"


def test_acl_replacement_and_revocation():
    """Scoped ACL replacement deletes old ACLs for the batch and revokes access when empty."""
    repo = InMemoryKnowledgeRepository()
    repo.claim_sync("SLACK", lease_token="tok-acl", lease_ttl_seconds=300)

    item = RawSourceItem(
        id="raw:slack:1",
        source_type=SourceType.SLACK,
        source_id="1",
        source_url="https://slack/1",
        title="Slack",
        raw_content="Text",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    acl1 = AclReference(
        resource_type="SOURCE_RECORD",
        resource_id="raw:slack:1",
        principal_type=PrincipalType.USER,
        principal_id="user_alice",
        permission="READ",
    )

    # Ingest with Alice ACL
    repo.persist_sync_batch(
        source_type="SLACK",
        lease_token="tok-acl",
        next_cursor="c1",
        items=[item],
        docs=[],
        chunks=[],
        acls=[acl1],
        entities=[],
        relationships=[],
    )
    assert len(repo.acls) == 1

    # Re-sync with Bob ACL instead
    acl2 = AclReference(
        resource_type="SOURCE_RECORD",
        resource_id="raw:slack:1",
        principal_type=PrincipalType.USER,
        principal_id="user_bob",
        permission="READ",
    )
    repo.persist_sync_batch(
        source_type="SLACK",
        lease_token="tok-acl",
        next_cursor="c2",
        items=[item],
        docs=[],
        chunks=[],
        acls=[acl2],
        entities=[],
        relationships=[],
    )
    assert len(repo.acls) == 1
    assert repo.acls[0].principal_id == "user_bob"


def test_shared_relationship_ownership_survives_single_owner_resync():
    """A relationship owned by both Record A and Record B survives if Record A re-syncs without it."""
    repo = InMemoryKnowledgeRepository()
    repo.claim_sync("GITHUB", lease_token="tok-shared", lease_ttl_seconds=300)

    item_a = RawSourceItem(
        id="sr-pr", source_type=SourceType.GITHUB, source_id="1", source_url="https://gh/pr/1",
        title="PR 1", raw_content="PR", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    item_b = RawSourceItem(
        id="sr-commit", source_type=SourceType.GITHUB, source_id="2", source_url="https://gh/commit/2",
        title="Commit 2", raw_content="Commit", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    ent_pr = Entity(id="pr:repo:1", entity_type=EntityType.PULL_REQUEST.value, name="PR 1", source_record_id="sr-pr")
    ent_commit = Entity(id="commit:repo:c2", entity_type=EntityType.COMMIT.value, name="C2", source_record_id="sr-commit")

    rel = Relationship(
        source_entity_id="pr:repo:1",
        target_entity_id="commit:repo:c2",
        relationship_type=RelationshipType.CONTAINS.value,
        metadata={"source_record_ids": ["sr-pr", "sr-commit"]},
    )

    # Ingest with both owners
    repo.persist_sync_batch(
        source_type="GITHUB",
        lease_token="tok-shared",
        next_cursor="c1",
        items=[item_a, item_b],
        docs=[], chunks=[], acls=[],
        entities=[ent_pr, ent_commit],
        relationships=[rel],
    )

    rel_key = ("pr:repo:1", "commit:repo:c2", RelationshipType.CONTAINS.value)
    assert repo.relationship_owners[rel_key] == {"sr-pr", "sr-commit"}

    # Now re-sync item_a without rel
    repo.persist_sync_batch(
        source_type="GITHUB",
        lease_token="tok-shared",
        next_cursor="c2",
        items=[item_a],
        docs=[], chunks=[], acls=[],
        entities=[ent_pr],
        relationships=[],  # PR dropped relationship
    )

    # Relationship must still exist, supported by sr-commit
    assert rel_key in repo.relationships
    assert repo.relationship_owners[rel_key] == {"sr-commit"}


def test_unauthorized_starting_entity_returns_empty_traversal():
    """An unauthorized starting entity immediately returns [] without traversing edges."""
    repo = InMemoryKnowledgeRepository()
    pr_secret = Entity(id="pr:repo:secret", entity_type=EntityType.PULL_REQUEST.value, name="Secret PR", source_record_id="sr-secret")
    commit_pub = Entity(id="commit:repo:c1", entity_type=EntityType.COMMIT.value, name="Commit", source_record_id="sr-pub")
    repo.save_entities([pr_secret, commit_pub])

    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-pub", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-secret", principal_type=PrincipalType.USER, principal_id="admin_user", permission="READ"),
    ])

    rel = Relationship(
        source_entity_id="pr:repo:secret",
        target_entity_id="commit:repo:c1",
        relationship_type=RelationshipType.CONTAINS.value,
        metadata={"source_record_id": "sr-secret"},
    )
    repo.save_relationships([rel])

    # Standard user has no access to starting entity
    results = repo.get_relationships_for_entity("pr:repo:secret", direction="OUTGOING", user_id="standard_user")
    assert results == []


def test_neighbor_entity_redacts_private_anchor_when_accessed_via_relationship():
    """Neighbor entity whose primary anchor is private has source_record_id redacted when accessed via supporting relationship."""
    repo = InMemoryKnowledgeRepository()

    # Public PR contains private commit
    pr_pub = Entity(id="pr:repo:10", entity_type=EntityType.PULL_REQUEST.value, name="Public PR 10", source_record_id="sr-pr-pub")
    commit_priv = Entity(
        id="commit:repo:c10",
        entity_type=EntityType.COMMIT.value,
        name="Private Commit",
        source_record_id="sr-commit-priv",
        metadata={"repository": "repo", "sha": "c10", "internal_security_tag": "confidential"},
    )
    repo.save_entities([pr_pub, commit_priv])

    # PR is public; commit source record is restricted to admin
    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-pr-pub", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-commit-priv", principal_type=PrincipalType.USER, principal_id="admin", permission="READ"),
    ])

    # Relationship owned by PR
    rel = Relationship(
        source_entity_id="pr:repo:10",
        target_entity_id="commit:repo:c10",
        relationship_type=RelationshipType.CONTAINS.value,
        metadata={"source_record_id": "sr-pr-pub"},
    )
    repo.save_relationships([rel])

    # Standard user traverses from public PR -> commit
    results = repo.get_relationships_for_entity("pr:repo:10", direction="OUTGOING", user_id="standard_user")
    assert len(results) == 1
    rel_out, neighbor = results[0]

    assert neighbor.id == "commit:repo:c10"
    # Private anchor identifier must be redacted to None
    assert neighbor.source_record_id is None
    # Private non-structural metadata must be absent
    assert "internal_security_tag" not in neighbor.metadata
    assert neighbor.metadata.get("sha") == "c10"


def test_entity_two_incident_edges_one_readable_owner_metadata_isolated():
    """When an entity has two incident edges and only one owner is readable, private metadata is strictly isolated."""
    repo = InMemoryKnowledgeRepository()

    ticket = Entity(
        id="ticket:FEAT-1",
        entity_type=EntityType.TICKET.value,
        name="FEAT-1",
        metadata={"ticket_id": "FEAT-1", "secret_exec_memo": "Do not disclose"},
    )
    pr_pub = Entity(id="pr:repo:1", entity_type=EntityType.PULL_REQUEST.value, name="Public PR", source_record_id="sr-pr-pub")
    slack_priv = Entity(id="slack:chan:1", entity_type=EntityType.SLACK_THREAD.value, name="Private Slack", source_record_id="sr-slack-priv")
    repo.save_entities([ticket, pr_pub, slack_priv])

    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-pr-pub", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-slack-priv", principal_type=PrincipalType.GROUP, principal_id="group_exec", permission="READ"),
    ])

    rel_pub = Relationship(
        source_entity_id="ticket:FEAT-1", target_entity_id="pr:repo:1",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
        metadata={"source_record_id": "sr-pr-pub"},
    )
    rel_priv = Relationship(
        source_entity_id="ticket:FEAT-1", target_entity_id="slack:chan:1",
        relationship_type=RelationshipType.DISCUSSED_IN.value,
        metadata={"source_record_id": "sr-slack-priv"},
    )
    repo.save_relationships([rel_pub, rel_priv])

    # Standard user traverses from PR to Ticket
    results = repo.get_relationships_for_entity("pr:repo:1", direction="INCOMING", user_id="standard_user")
    assert len(results) == 1
    rel_out, neighbor_ticket = results[0]

    assert neighbor_ticket.id == "ticket:FEAT-1"
    # Metadata isolated: secret memo is stripped
    assert "secret_exec_memo" not in neighbor_ticket.metadata
    assert neighbor_ticket.metadata.get("ticket_id") == "FEAT-1"


def test_unowned_legacy_edge_hidden_from_traversal_even_if_endpoints_public():
    """An unowned legacy edge with two public endpoints is strictly hidden from traversal."""
    repo = InMemoryKnowledgeRepository()

    pr_pub = Entity(id="pr:repo:50", entity_type=EntityType.PULL_REQUEST.value, name="PR 50", source_record_id="sr-pr-50")
    commit_pub = Entity(id="commit:repo:c50", entity_type=EntityType.COMMIT.value, name="Commit 50", source_record_id="sr-commit-50")
    repo.save_entities([pr_pub, commit_pub])

    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-pr-50", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="sr-commit-50", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
    ])

    # Save relationship directly with 0 owners in relationship_owners
    key = ("pr:repo:50", "commit:repo:c50", RelationshipType.CONTAINS.value)
    repo.relationships[key] = Relationship(
        source_entity_id="pr:repo:50",
        target_entity_id="commit:repo:c50",
        relationship_type=RelationshipType.CONTAINS.value,
        metadata={"repository": "repo", "sha": "c50", "pr_number": "50"},
    )
    # Ensure relationship_owners is explicitly empty for this unowned legacy edge
    repo.relationship_owners[key] = set()

    # Traversal must conceal the edge even though both endpoints are publicly visible!
    results = repo.get_relationships_for_entity("pr:repo:50", direction="OUTGOING", user_id="anyone")
    assert results == []
