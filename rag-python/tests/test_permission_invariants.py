"""Comprehensive permission invariant and property-style security tests.

Covers:
(a) Graph boost never surfaces an unauthorized doc linked via an entity to an authorized doc.
(b) Removing ACL rows or changing user groups makes previously visible results disappear.
(c) Deleted documents never return from lexical, vector, hybrid, or /ask.
(d) /ask never cites a chunk outside the user's authorized set.
(e) 1% access user retrieves permitted chunks without missing results or leakage.
(f) Property-style test across many random users comparing returned chunk IDs against
    an independent raw SQL authorization query.
"""

import random
from datetime import datetime, timezone
from typing import List, Optional, Set

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.dependencies import get_grounded_rag_service, get_hybrid_retriever, get_repository
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.repository import InMemoryKnowledgeRepository, PostgresKnowledgeRepository
from app.main import create_app
from app.normalization.models import CanonicalDocument
from app.rag.reranker import DeterministicReranker
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever


def _detect_test_postgres_url() -> Optional[str]:
    from app.common.config import get_settings

    settings = get_settings()
    candidates = [
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/test_knowledge",
        "postgresql://knowledge:local_dev_only_change_me@127.0.0.1:5432/test_knowledge",
        "postgresql://knowledge:local_dev_only_change_me@localhost:5432/test_knowledge",
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


LIVE_TEST_PG_URL = _detect_test_postgres_url()


def _seed_doc(
    repo,
    doc_id: str,
    content: str,
    acls: List[AclReference],
    source_type: str = "GITHUB",
    url: Optional[str] = None,
    embedding: Optional[List[float]] = None,
) -> CanonicalChunk:
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    sr_id = f"sr:{doc_id}"
    doc_url = url or f"https://company.internal/docs/{doc_id}"
    raw_item = RawSourceItem(
        id=sr_id,
        source_type=SourceType(source_type),
        source_id=doc_id,
        source_url=doc_url,
        title=f"Title {doc_id}",
        raw_content=content,
        created_at=now,
        updated_at=now,
    )
    doc = CanonicalDocument(
        id=doc_id,
        source_record_id=sr_id,
        source_type=source_type,
        title=f"Title {doc_id}",
        content=content,
        author="engineer",
        url=doc_url,
        created_at=now,
        updated_at=now,
    )
    embedder = MockEmbeddingProvider(dimension=384)
    vec = embedding if embedding is not None else embedder.embed_query(content)
    chunk = CanonicalChunk(
        id=f"chunk:{doc_id}:0",
        document_id=doc_id,
        chunk_index=0,
        content=content,
        token_count=max(1, len(content.split())),
        content_hash=CanonicalChunk.compute_hash(content),
        embedding=vec,
        created_at=now,
    )
    repo.save_source_records([raw_item])
    repo.save_documents([doc])
    repo.save_chunks([chunk])
    repo.save_acls(acls)
    return chunk


# ---------------------------------------------------------------------------
# (a) Graph boost must not surface an unauthorized doc linked via entity
# ---------------------------------------------------------------------------

def test_graph_boost_never_surfaces_unauthorized_linked_doc():
    repo = InMemoryKnowledgeRepository()
    embedder = MockEmbeddingProvider(dimension=384)

    auth_doc_id = "doc:github:org/core:pr:101"
    secret_doc_id = "doc:github:org/core:commit:deadbeef12"

    _seed_doc(
        repo,
        doc_id=auth_doc_id,
        content="DC-7001 validation gateway rollout approved for engineering",
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id=auth_doc_id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_engineering",
                permission="READ",
            )
        ],
    )
    _seed_doc(
        repo,
        doc_id=secret_doc_id,
        content="DC-7001 secret cryptographic key rotation commit deadbeef12",
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id=secret_doc_id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_security_only",
                permission="READ",
            )
        ],
    )

    # Link authorized PR to unauthorized commit in the knowledge graph
    repo.save_entities(
        [
            Entity(
                id="pr:org/core:101",
                entity_type=EntityType.PULL_REQUEST.value,
                name="PR #101",
                source_record_id=f"sr:{auth_doc_id}",
            ),
            Entity(
                id="commit:org/core:deadbeef12",
                entity_type=EntityType.COMMIT.value,
                name="deadbeef12",
                source_record_id=f"sr:{secret_doc_id}",
            ),
            Entity(
                id="ticket:DC-7001",
                entity_type=EntityType.TICKET.value,
                name="DC-7001",
                source_record_id=f"sr:{auth_doc_id}",
            ),
        ]
    )
    repo.save_relationships(
        [
            Relationship(
                source_entity_id="ticket:DC-7001",
                target_entity_id="pr:org/core:101",
                relationship_type=RelationshipType.IMPLEMENTED_BY.value,
                source_record_id=f"sr:{auth_doc_id}",
            ),
            Relationship(
                source_entity_id="pr:org/core:101",
                target_entity_id="commit:org/core:deadbeef12",
                relationship_type=RelationshipType.CONTAINS.value,
                source_record_id=f"sr:{auth_doc_id}",
            ),
        ]
    )

    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)
    reranker = DeterministicReranker(repository=repo)

    candidates = retriever.search("DC-7001", limit=10, user_id="alice", group_ids=["group_engineering"])
    reranked = reranker.rerank("DC-7001", candidates, user_id="alice", group_ids=["group_engineering"])

    returned_docs = {r.document_id for r in candidates} | {r.document_id for r in reranked}
    assert auth_doc_id in returned_docs
    assert secret_doc_id not in returned_docs


# ---------------------------------------------------------------------------
# (b) After ACL rows are removed or user's groups change, results disappear
# ---------------------------------------------------------------------------

def test_results_disappear_when_acl_removed_or_groups_change():
    repo = InMemoryKnowledgeRepository()
    embedder = MockEmbeddingProvider(dimension=384)
    doc_id = "doc:finance:q4-plan"

    _seed_doc(
        repo,
        doc_id=doc_id,
        content="Confidential Q4 acquisition budget target",
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id=doc_id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_finance",
                permission="READ",
            ),
            AclReference(
                resource_type="DOCUMENT",
                resource_id=doc_id,
                principal_type=PrincipalType.USER,
                principal_id="carol",
                permission="READ",
            ),
        ],
    )
    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)

    # 1. Group membership grants access -> removed group revokes access
    assert len(retriever.search("acquisition budget", user_id="bob", group_ids=["group_finance"])) == 1
    assert len(retriever.search("acquisition budget", user_id="bob", group_ids=["group_engineering"])) == 0

    # 2. Direct user ACL grants access -> removing ACL rows revokes access
    assert len(retriever.search("acquisition budget", user_id="carol", group_ids=[])) == 1
    repo.acls.clear()
    assert len(retriever.search("acquisition budget", user_id="carol", group_ids=[])) == 0
    assert len(retriever.search("acquisition budget", user_id="bob", group_ids=["group_finance"])) == 0


# ---------------------------------------------------------------------------
# (c) Deleted docs never return
# ---------------------------------------------------------------------------

def test_deleted_docs_never_return_in_memory():
    repo = InMemoryKnowledgeRepository()
    embedder = MockEmbeddingProvider(dimension=384)
    doc_id = "doc:deleted-incident-postmortem"
    chunk = _seed_doc(
        repo,
        doc_id=doc_id,
        content="Incident postmortem unique_canary_token_9911",
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id=doc_id,
                principal_type=PrincipalType.PUBLIC,
                principal_id="*",
                permission="READ",
            )
        ],
    )
    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)
    assert len(retriever.search("unique_canary_token_9911", user_id="anyone")) == 1

    # Simulate document deletion
    del repo.documents[doc_id]
    del repo.chunks[chunk.id]

    assert repo.search_lexical("unique_canary_token_9911", user_id="anyone") == []
    assert repo.search_vector(embedder.embed_query("unique_canary_token_9911"), user_id="anyone") == []
    assert retriever.search("unique_canary_token_9911", user_id="anyone") == []


# ---------------------------------------------------------------------------
# (d) /ask never cites a chunk outside the user's authorized set
# ---------------------------------------------------------------------------

def test_ask_never_cites_unauthorized_chunk():
    repo = InMemoryKnowledgeRepository()
    embedder = MockEmbeddingProvider(dimension=384)

    auth_url = "https://github.com/org/repo/pull/55"
    secret_url = "https://mail.company.internal/mail/ceo/secret-acquisition"

    _seed_doc(
        repo,
        doc_id="doc:public-arch",
        content="Phoenix deployment rollback uses canary checks before promoting traffic.",
        url=auth_url,
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id="doc:public-arch",
                principal_type=PrincipalType.GROUP,
                principal_id="group_engineering",
                permission="READ",
            )
        ],
    )
    _seed_doc(
        repo,
        doc_id="doc:secret-exec",
        content="Phoenix confidential executive acquisition price is 950M USD SECRET_CANARY_XYZ.",
        source_type="EMAIL",
        url=secret_url,
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id="doc:secret-exec",
                principal_type=PrincipalType.GROUP,
                principal_id="group_executive",
                permission="READ",
            )
        ],
    )

    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)
    rag_service = GroundedRagService(retriever=retriever)
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    app.dependency_overrides[get_grounded_rag_service] = lambda: rag_service

    client = TestClient(app)

    # Authorized engineer asks about Phoenix: can only cite auth_url, never secret_url or SECRET_CANARY_XYZ
    resp = client.post(
        "/api/v1/ask",
        json={"question": "What is the Phoenix secret acquisition price and rollback?"},
        headers={"X-User-Id": "eng_1", "X-User-Groups": "group_engineering"},
    )
    assert resp.status_code == 200
    body = resp.json()
    cited_urls = {c["url"] for c in body["citations"]}
    assert secret_url not in cited_urls
    assert "SECRET_CANARY_XYZ" not in body["answer"]
    if cited_urls:
        assert cited_urls == {auth_url}

    # Completely unauthorized intern gets INSUFFICIENT_EVIDENCE and 0 citations
    resp_unauth = client.post(
        "/api/v1/ask",
        json={"question": "What is the Phoenix secret acquisition price?"},
        headers={"X-User-Id": "intern_1", "X-User-Groups": "group_interns"},
    )
    assert resp_unauth.status_code == 200
    unauth_body = resp_unauth.json()
    assert unauth_body["status"] == "INSUFFICIENT_EVIDENCE"
    assert unauth_body["citations"] == []
    assert "SECRET_CANARY_XYZ" not in unauth_body["answer"]


# ---------------------------------------------------------------------------
# (e) 1% access user retrieval without recall drop or leakage
# ---------------------------------------------------------------------------

def test_one_percent_access_user_gets_results_and_no_leak():
    repo = InMemoryKnowledgeRepository()
    embedder = MockEmbeddingProvider(dimension=384)
    query_vec = embedder.embed_query("distributed consensus heartbeat timeout")

    for i in range(100):
        doc_id = f"doc:corpus:{i:03d}"
        is_target = i == 77
        acls = [
            AclReference(
                resource_type="DOCUMENT",
                resource_id=doc_id,
                principal_type=PrincipalType.USER if is_target else PrincipalType.GROUP,
                principal_id="low_access_user" if is_target else "group_all_others",
                permission="READ",
            )
        ]
        _seed_doc(
            repo,
            doc_id=doc_id,
            content=f"Distributed consensus heartbeat timeout document {i}",
            acls=acls,
            embedding=query_vec,  # identical vectors so top-K would saturate on unauthorized docs if broken
        )

    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)
    results = retriever.search("distributed consensus heartbeat timeout", limit=10, user_id="low_access_user", group_ids=[])
    assert len(results) == 1
    assert results[0].document_id == "doc:corpus:077"


# ---------------------------------------------------------------------------
# (f) Live PostgreSQL tests: (a), (b), (c), and property-style raw SQL check
# ---------------------------------------------------------------------------

def _truncate_test_pg(url: str) -> None:
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
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
                """
            )
        conn.commit()


@pytest.mark.skipif(LIVE_TEST_PG_URL is None, reason="Requires live PostgreSQL test_knowledge database")
def test_live_postgres_acl_removal_and_doc_deletion():
    """Verify live PostgreSQL (b) ACL removal / group change and (c) doc deletion never return results."""
    _truncate_test_pg(LIVE_TEST_PG_URL)
    repo = PostgresKnowledgeRepository(LIVE_TEST_PG_URL)
    embedder = MockEmbeddingProvider(dimension=384)
    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)

    _seed_doc(
        repo,
        doc_id="doc-live-acl",
        content="Live database ACL revocation canary_term_alpha",
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id="doc-live-acl",
                principal_type=PrincipalType.GROUP,
                principal_id="group_security",
                permission="READ",
            )
        ],
    )

    assert len(retriever.search("canary_term_alpha", user_id="u1", group_ids=["group_security"])) == 1
    # User groups change -> disappears
    assert retriever.search("canary_term_alpha", user_id="u1", group_ids=["group_engineering"]) == []

    # Remove ACL rows directly in PostgreSQL -> disappears even with group_security
    with psycopg.connect(LIVE_TEST_PG_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM acl_references WHERE resource_id = 'doc-live-acl';")
        conn.commit()
    assert retriever.search("canary_term_alpha", user_id="u1", group_ids=["group_security"]) == []

    # Delete document -> never returns
    _seed_doc(
        repo,
        doc_id="doc-live-delete",
        content="Live database deletion canary_term_beta",
        acls=[
            AclReference(
                resource_type="DOCUMENT",
                resource_id="doc-live-delete",
                principal_type=PrincipalType.PUBLIC,
                principal_id="*",
                permission="READ",
            )
        ],
    )
    assert len(retriever.search("canary_term_beta", user_id="u2")) == 1
    with psycopg.connect(LIVE_TEST_PG_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = 'doc-live-delete';")
        conn.commit()
    assert repo.search_lexical("canary_term_beta", user_id="u2") == []
    assert repo.search_vector(embedder.embed_query("canary_term_beta"), user_id="u2") == []
    assert retriever.search("canary_term_beta", user_id="u2") == []


@pytest.mark.skipif(LIVE_TEST_PG_URL is None, reason="Requires live PostgreSQL test_knowledge database")
def test_property_random_users_never_exceed_raw_sql_authorized_set():
    """Property-style test: for 25 random users, every returned chunk_id must be in the raw SQL authorized set."""
    _truncate_test_pg(LIVE_TEST_PG_URL)
    repo = PostgresKnowledgeRepository(LIVE_TEST_PG_URL)
    embedder = MockEmbeddingProvider(dimension=384)
    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)

    rng = random.Random(20261112)
    groups_pool = ["group_eng", "group_fin", "group_sec", "group_ops", "group_exec"]
    users_pool = [f"rand_user_{i}" for i in range(10)]
    topics = ["payment validation", "database failover", "token expiry", "audit trail", "cache invalidation"]

    # Seed 60 multi-tenant documents with heterogeneous ACL combinations
    for idx in range(60):
        doc_id = f"prop-doc-{idx:03d}"
        topic = topics[idx % len(topics)]
        acls: List[AclReference] = []
        mode = idx % 5
        if mode == 0:
            acls.append(
                AclReference(
                    resource_type="DOCUMENT",
                    resource_id=doc_id,
                    principal_type=PrincipalType.PUBLIC,
                    principal_id="*",
                    permission="READ",
                )
            )
        elif mode == 1:
            u = users_pool[idx % len(users_pool)]
            acls.append(
                AclReference(
                    resource_type="DOCUMENT",
                    resource_id=doc_id,
                    principal_type=PrincipalType.USER,
                    principal_id=u,
                    permission="READ",
                )
            )
        elif mode == 2:
            g = groups_pool[idx % len(groups_pool)]
            acls.append(
                AclReference(
                    resource_type="DOCUMENT",
                    resource_id=doc_id,
                    principal_type=PrincipalType.GROUP,
                    principal_id=g,
                    permission="READ",
                )
            )
        elif mode == 3:
            # WRITE-only ACL must NOT grant read access
            acls.append(
                AclReference(
                    resource_type="DOCUMENT",
                    resource_id=doc_id,
                    principal_type=PrincipalType.PUBLIC,
                    principal_id="*",
                    permission="WRITE",
                )
            )
        else:
            # Multi-group / chunk-level ACL
            g1, g2 = rng.sample(groups_pool, 2)
            acls.append(
                AclReference(
                    resource_type="CHUNK",
                    resource_id=f"chunk:{doc_id}:0",
                    principal_type=PrincipalType.GROUP,
                    principal_id=g1,
                    permission="READ",
                )
            )
            acls.append(
                AclReference(
                    resource_type="SOURCE_RECORD",
                    resource_id=f"sr:{doc_id}",
                    principal_type=PrincipalType.GROUP,
                    principal_id=g2,
                    permission="READ",
                )
            )

        _seed_doc(
            repo,
            doc_id=doc_id,
            content=f"Property verification content about {topic} item {idx}",
            acls=acls,
        )

    raw_auth_sql = """
        SELECT DISTINCT c.id
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE EXISTS (
            SELECT 1 FROM acl_references a
            WHERE UPPER(a.permission) = 'READ'
              AND (
                  (a.resource_type = 'SOURCE_RECORD' AND a.resource_id = d.source_record_id)
                  OR (a.resource_type = 'DOCUMENT' AND a.resource_id = d.id)
                  OR (a.resource_type = 'CHUNK' AND a.resource_id = c.id)
              )
              AND (
                  a.principal_type = 'PUBLIC'
                  OR (a.principal_type = 'USER' AND a.principal_id = %s)
                  OR (a.principal_type = 'GROUP' AND a.principal_id = ANY(%s))
              )
        );
    """

    with psycopg.connect(LIVE_TEST_PG_URL) as conn:
        for step in range(25):
            uid = rng.choice(users_pool + ["outsider_user"])
            g_count = rng.randint(0, 3)
            gids = rng.sample(groups_pool, g_count)
            query_text = rng.choice(topics)
            query_vec = embedder.embed_query(query_text)

            with conn.cursor() as cur:
                cur.execute(raw_auth_sql, (uid, gids))
                expected_authorized_ids: Set[str] = {r[0] for r in cur.fetchall()}

            lex_ids = {r.chunk_id for r in repo.search_lexical(query_text, limit=15, user_id=uid, group_ids=gids)}
            vec_ids = {r.chunk_id for r in repo.search_vector(query_vec, limit=15, user_id=uid, group_ids=gids)}
            hyb_ids = {r.chunk_id for r in retriever.search(query_text, limit=15, user_id=uid, group_ids=gids)}

            assert lex_ids.issubset(expected_authorized_ids), f"Lexical leak for user={uid} groups={gids}"
            assert vec_ids.issubset(expected_authorized_ids), f"Vector leak for user={uid} groups={gids}"
            assert hyb_ids.issubset(expected_authorized_ids), f"Hybrid leak for user={uid} groups={gids}"
