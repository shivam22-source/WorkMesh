"""Comprehensive security tests for ACL permission enforcement (AD-04).

Proves that:
1. Authorized user can retrieve permitted content.
2. Authorized group can retrieve permitted content.
3. PUBLIC READ works only when explicitly configured.
4. Unauthorized users receive no restricted content (empty results).
5. Missing ACL denies access (deny-by-default).
6. WRITE-only permission does not grant READ access.
7. One user's group membership does not leak into another user's search.
8. Mixed authorized and unauthorized candidates return only authorized chunks.
9. Lexical, vector, and hybrid search all enforce the same rules.
10. Canary secret strings never appear in unauthorized search results.
11. Filtering happens before candidate limits (unauthorized candidates do not consume limit quota).
12. SQL where clause generator builds secure, parameterized expressions matching memory semantics.
"""

from datetime import datetime, timezone
from typing import List, Optional

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.repository import InMemoryKnowledgeRepository
from app.normalization.models import CanonicalDocument
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.lexical import LexicalRetriever
from app.security.acl import build_acl_where_clause, has_read_permission

# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _populate_test_document(
    repo: InMemoryKnowledgeRepository,
    doc_id: str,
    content: str,
    acls: List[AclReference],
    source_type: str = "GITHUB",
    embedding: Optional[List[float]] = None,
) -> CanonicalChunk:
    """Helper to register a raw source item, document, chunk, and ACLs in repository."""
    source_id = f"raw:{doc_id}"
    raw_item = RawSourceItem(
        id=source_id,
        source_type=SourceType.GITHUB if source_type == "GITHUB" else SourceType.SLACK,
        source_id=doc_id,
        source_url=f"https://company.internal/docs/{doc_id}",
        title=f"Doc {doc_id}",
        raw_content=content,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    doc = CanonicalDocument(
        id=doc_id,
        source_record_id=source_id,
        source_type=source_type,
        title=f"Doc {doc_id}",
        content=content,
        url=f"https://company.internal/docs/{doc_id}",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    chunk = CanonicalChunk(
        id=f"chunk:{doc_id}:0",
        document_id=doc_id,
        chunk_index=0,
        content=content,
        token_count=len(content.split()),
        content_hash=CanonicalChunk.compute_hash(content),
        embedding=embedding,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repo.save_source_records([raw_item])
    repo.save_documents([doc])
    repo.save_chunks([chunk])
    repo.save_acls(acls)
    return chunk


# ---------------------------------------------------------------------------
# 1. Pure Unit Tests: has_read_permission
# ---------------------------------------------------------------------------

def test_has_read_permission_deny_by_default_when_no_acls():
    assert has_read_permission([], user_id="alice", group_ids=["eng"]) is False
    assert has_read_permission([], user_id=None, group_ids=None) is False


def test_has_read_permission_public_read_grants_access():
    acl = AclReference(
        resource_type="SOURCE_RECORD",
        resource_id="res1",
        principal_type=PrincipalType.PUBLIC,
        principal_id="*",
        permission="READ",
    )
    assert has_read_permission([acl], user_id=None, group_ids=None) is True
    assert has_read_permission([acl], user_id="guest", group_ids=[]) is True


def test_has_read_permission_write_only_does_not_grant_read():
    acl = AclReference(
        resource_type="SOURCE_RECORD",
        resource_id="res1",
        principal_type=PrincipalType.USER,
        principal_id="alice",
        permission="WRITE",
    )
    assert has_read_permission([acl], user_id="alice", group_ids=["eng"]) is False


def test_has_read_permission_user_match():
    acl = AclReference(
        resource_type="SOURCE_RECORD",
        resource_id="res1",
        principal_type=PrincipalType.USER,
        principal_id="alice",
        permission="READ",
    )
    assert has_read_permission([acl], user_id="alice") is True
    assert has_read_permission([acl], user_id="bob") is False
    assert has_read_permission([acl], user_id=None) is False


def test_has_read_permission_group_match():
    acl = AclReference(
        resource_type="SOURCE_RECORD",
        resource_id="res1",
        principal_type=PrincipalType.GROUP,
        principal_id="group_eng",
        permission="READ",
    )
    assert has_read_permission([acl], group_ids=["group_eng", "group_backend"]) is True
    assert has_read_permission([acl], group_ids=["group_marketing"]) is False
    assert has_read_permission([acl], group_ids=[]) is False
    assert has_read_permission([acl], group_ids=None) is False


# ---------------------------------------------------------------------------
# 2. SQL WHERE Clause Generator: build_acl_where_clause
# ---------------------------------------------------------------------------

def test_sql_builder_public_only_when_no_identity():
    clause, params = build_acl_where_clause(user_id=None, group_ids=None)
    assert "UPPER(a.permission) = 'READ'" in clause
    assert "a.principal_type = 'PUBLIC'" in clause
    assert "a.principal_type = 'USER'" not in clause
    assert "a.principal_type = 'GROUP'" not in clause
    assert params == []


def test_sql_builder_user_and_group_parameterization():
    clause, params = build_acl_where_clause(
        user_id="employee_42",
        group_ids=["group_eng", "group_backend"],
    )
    assert "a.principal_type = 'PUBLIC'" in clause
    assert "(a.principal_type = 'USER' AND a.principal_id = %s)" in clause
    assert "(a.principal_type = 'GROUP' AND a.principal_id = ANY(%s))" in clause
    assert params == ["employee_42", ["group_eng", "group_backend"]]


# ---------------------------------------------------------------------------
# 3. Repository Lexical Search ACL Enforcement
# ---------------------------------------------------------------------------

def test_lexical_authorized_user_retrieves_content():
    repo = InMemoryKnowledgeRepository()
    acl = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_user_only",
            principal_type=PrincipalType.USER,
            principal_id="employee_alice",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_user_only", "Secret architecture specs for authentication", acl)

    # Alice can retrieve
    results_alice = repo.search_lexical("authentication", user_id="employee_alice")
    assert len(results_alice) == 1
    assert results_alice[0].document_id == "doc_user_only"

    # Bob cannot retrieve
    results_bob = repo.search_lexical("authentication", user_id="employee_bob")
    assert len(results_bob) == 0


def test_lexical_authorized_group_retrieves_content():
    repo = InMemoryKnowledgeRepository()
    acl = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_eng_only",
            principal_type=PrincipalType.GROUP,
            principal_id="group_engineering",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_eng_only", "Kubernetes cluster production deployment guides", acl)

    # Engineering member retrieves
    results_eng = repo.search_lexical("deployment", group_ids=["group_engineering"])
    assert len(results_eng) == 1

    # Marketing member receives nothing
    results_mkt = repo.search_lexical("deployment", group_ids=["group_marketing"])
    assert len(results_mkt) == 0


def test_lexical_public_read_accessible_by_anyone():
    repo = InMemoryKnowledgeRepository()
    acl = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_public",
            principal_type=PrincipalType.PUBLIC,
            principal_id="*",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_public", "Company wide holiday calendar announcement", acl)

    # Anonymous / empty credentials can retrieve
    results_anon = repo.search_lexical("holiday", user_id=None, group_ids=None)
    assert len(results_anon) == 1

    # User with unrelated group can retrieve
    results_user = repo.search_lexical("holiday", user_id="employee_random", group_ids=["group_sales"])
    assert len(results_user) == 1


def test_lexical_missing_acl_denies_access():
    repo = InMemoryKnowledgeRepository()
    # Ingest document with NO ACLs at all
    _populate_test_document(repo, "doc_orphan", "Orphaned document without explicit permissions", [])

    # Any caller is denied access by default
    assert repo.search_lexical("Orphaned", user_id="employee_alice", group_ids=["group_engineering"]) == []
    assert repo.search_lexical("Orphaned", user_id=None, group_ids=None) == []


def test_lexical_write_only_permission_denies_read():
    repo = InMemoryKnowledgeRepository()
    acl = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_write",
            principal_type=PrincipalType.USER,
            principal_id="employee_alice",
            permission="WRITE",
        )
    ]
    _populate_test_document(repo, "doc_write", "Audit logging internal write buffer", acl)

    # Alice has WRITE but not READ
    results = repo.search_lexical("logging", user_id="employee_alice")
    assert len(results) == 0


def test_group_isolation_no_leakage_between_users():
    repo = InMemoryKnowledgeRepository()
    acl_finance = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_fin",
            principal_type=PrincipalType.GROUP,
            principal_id="group_finance",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_fin", "Quarterly revenue and fiscal budget projections", acl_finance)

    # Finance user sees it
    res_fin = repo.search_lexical("revenue", user_id="user_fin", group_ids=["group_finance"])
    assert len(res_fin) == 1

    # Eng user searching same term sees nothing
    res_eng = repo.search_lexical("revenue", user_id="user_eng", group_ids=["group_engineering"])
    assert len(res_eng) == 0


def test_mixed_authorized_and_unauthorized_candidates():
    repo = InMemoryKnowledgeRepository()

    # Doc 1: Authorized for Engineering
    acl_eng = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_eng",
            principal_type=PrincipalType.GROUP,
            principal_id="group_engineering",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_eng", "Database schema migration checklist and rollback", acl_eng)

    # Doc 2: Restricted to Executive
    acl_exec = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_exec",
            principal_type=PrincipalType.GROUP,
            principal_id="group_executive",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_exec", "Database acquisition budget and confidential executive review", acl_exec)

    # Search as engineering user
    results = repo.search_lexical("database", group_ids=["group_engineering"])
    assert len(results) == 1
    assert results[0].document_id == "doc_eng"
    assert "doc_exec" not in {r.document_id for r in results}


# ---------------------------------------------------------------------------
# 4. Vector Search ACL Enforcement
# ---------------------------------------------------------------------------

def test_vector_search_enforces_acl():
    provider = MockEmbeddingProvider()
    repo = InMemoryKnowledgeRepository()

    # Secret document for security team only
    emb_secret = provider.embed_query("zero trust network segmentation")
    acl_sec = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_sec",
            principal_type=PrincipalType.GROUP,
            principal_id="group_security",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_sec", "zero trust network segmentation policy", acl_sec, embedding=emb_secret)

    # Public document
    emb_pub = provider.embed_query("public network guidelines")
    acl_pub = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_pub",
            principal_type=PrincipalType.PUBLIC,
            principal_id="*",
            permission="READ",
        )
    ]
    _populate_test_document(repo, "doc_pub", "public network guidelines and remote work", acl_pub, embedding=emb_pub)

    # Query vector
    query_emb = provider.embed_query("zero trust network")

    # Unauthorized user gets only public document
    results_unauth = repo.search_vector(query_emb, user_id="user_dev", group_ids=["group_frontend"])
    assert all(r.document_id != "doc_sec" for r in results_unauth)

    # Security user gets secret document
    results_auth = repo.search_vector(query_emb, user_id="user_sec", group_ids=["group_security"])
    doc_ids = {r.document_id for r in results_auth}
    assert "doc_sec" in doc_ids


# ---------------------------------------------------------------------------
# 5. Hybrid Search ACL Enforcement & Canary Secret Isolation
# ---------------------------------------------------------------------------

def test_hybrid_search_canary_secret_never_leaks_to_unauthorized_user():
    provider = MockEmbeddingProvider()
    repo = InMemoryKnowledgeRepository()
    canary = "CANARY_SECRET_ALPHA_TOKEN_9981442"

    emb_secret = provider.embed_query(f"confidential project details {canary}")
    acl_secret = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:doc_confidential",
            principal_type=PrincipalType.GROUP,
            principal_id="group_super_admin",
            permission="READ",
        )
    ]
    _populate_test_document(
        repo,
        "doc_confidential",
        f"Confidential project launch key: {canary} do not disclose",
        acl_secret,
        embedding=emb_secret,
    )

    retriever = HybridRetriever(repository=repo)

    # Unauthorized user searching for exact canary token
    unauth_results = retriever.search(
        canary,
        limit=10,
        user_id="standard_employee",
        group_ids=["group_engineering"],
    )

    # Proof of zero leakage
    assert len(unauth_results) == 0
    assert not any(canary in r.snippet for r in unauth_results)

    # Authorized super admin can retrieve it
    auth_results = retriever.search(
        canary,
        limit=10,
        user_id="super_admin",
        group_ids=["group_super_admin"],
    )
    assert len(auth_results) > 0
    assert any(canary in r.snippet for r in auth_results)


# ---------------------------------------------------------------------------
# 6. Pre-Limit Filtering Proof
# ---------------------------------------------------------------------------

def test_filtering_occurs_before_candidate_limits():
    """Prove that unauthorized high-scoring documents do not exhaust candidate limit.

    If candidate limit is 2, and the 5 top matches are unauthorized,
    the authorized 6th match must still be returned.
    """
    repo = InMemoryKnowledgeRepository()

    # 5 high-scoring unauthorized documents
    for i in range(5):
        doc_id = f"unauthorized_{i}"
        acl_denied = [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=f"raw:{doc_id}",
                principal_type=PrincipalType.GROUP,
                principal_id="group_restricted",
                permission="READ",
            )
        ]
        _populate_test_document(
            repo,
            doc_id,
            f"payment token processor implementation guide exact match payment {i}",
            acl_denied,
        )

    # 1 authorized document with lower term frequency
    acl_allowed = [
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:authorized_doc",
            principal_type=PrincipalType.GROUP,
            principal_id="group_engineering",
            permission="READ",
        )
    ]
    _populate_test_document(
        repo,
        "authorized_doc",
        "payment basic info",
        acl_allowed,
    )

    # Search with limit=2
    retriever = LexicalRetriever(repo)
    results = retriever.search(
        "payment",
        limit=2,
        user_id="alice",
        group_ids=["group_engineering"],
    )

    # The authorized document MUST be returned; unauthorized items must not consume the limit
    assert len(results) == 1
    assert results[0].document_id == "authorized_doc"
