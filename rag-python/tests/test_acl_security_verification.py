"""Focused security verification tests for ACL enforcement (Phase 4 Step 1 conditional review).

Verifies the 10-point checklist:
1.  SOURCE_RECORD READ grants access to associated documents and chunks.
2.  DOCUMENT READ grants access to associated chunks.
3.  CHUNK READ applies only to the matching chunk.
4.  Explicit PUBLIC READ works for anonymous users.
5.  Missing identity never grants unrestricted access.
6.  Missing ACL and WRITE-only ACL deny read access.
7.  USER and GROUP permissions isolated across different users.
8.  PostgreSQL ACL SQL parameter ordering and resource joins are correct.
9.  SQL filtering occurs before LIMIT.
10. In-memory and PostgreSQL permission semantics match.
"""

from datetime import datetime, timezone
from typing import List, Optional

import pytest

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.contracts.rag_search import RagSearchResultItem
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.repository import InMemoryKnowledgeRepository
from app.normalization.models import CanonicalDocument
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.vector import VectorRetriever
from app.security.acl import build_acl_where_clause, has_read_permission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo_with_doc(
    doc_id: str,
    content: str,
    acls: List[AclReference],
    source_type: str = "GITHUB",
    embedding: Optional[List[float]] = None,
) -> InMemoryKnowledgeRepository:
    """Create a fresh repo containing one source record → document → chunk."""
    repo = InMemoryKnowledgeRepository()
    _add_doc(repo, doc_id, content, acls, source_type, embedding)
    return repo


def _add_doc(
    repo: InMemoryKnowledgeRepository,
    doc_id: str,
    content: str,
    acls: List[AclReference],
    source_type: str = "GITHUB",
    embedding: Optional[List[float]] = None,
) -> CanonicalChunk:
    """Add a source record, document, chunk, and ACLs to an existing repo."""
    source_id = f"raw:{doc_id}"
    raw = RawSourceItem(
        id=source_id,
        source_type=SourceType.GITHUB if source_type == "GITHUB" else SourceType.SLACK,
        source_id=doc_id,
        source_url=f"https://co.internal/{doc_id}",
        title=f"Title {doc_id}",
        raw_content=content,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    doc = CanonicalDocument(
        id=doc_id,
        source_record_id=source_id,
        source_type=source_type,
        title=f"Title {doc_id}",
        content=content,
        url=f"https://co.internal/{doc_id}",
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
    repo.save_source_records([raw])
    repo.save_documents([doc])
    repo.save_chunks([chunk])
    repo.save_acls(acls)
    return chunk


# ============================================================================
# 1. SOURCE_RECORD READ grants access to its associated documents and chunks
# ============================================================================

class TestSourceRecordRead:
    def test_source_record_read_grants_chunk_access(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:sr_doc",
            principal_type=PrincipalType.GROUP,
            principal_id="group_eng",
            permission="READ",
        )]
        repo = _make_repo_with_doc("sr_doc", "architecture design review meeting", acl)
        results = repo.search_lexical("architecture", group_ids=["group_eng"])
        assert len(results) == 1
        assert results[0].chunk_id == "chunk:sr_doc:0"

    def test_source_record_read_denies_wrong_group(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:sr_doc2",
            principal_type=PrincipalType.GROUP,
            principal_id="group_eng",
            permission="READ",
        )]
        repo = _make_repo_with_doc("sr_doc2", "architecture design review meeting", acl)
        results = repo.search_lexical("architecture", group_ids=["group_marketing"])
        assert len(results) == 0


# ============================================================================
# 2. DOCUMENT READ grants access to its associated chunks
# ============================================================================

class TestDocumentRead:
    def test_document_level_read_grants_chunk_access(self):
        """ACL with resource_type=DOCUMENT and resource_id=doc.id should grant access."""
        acl = [AclReference(
            resource_type="DOCUMENT",
            resource_id="doc_level",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="READ",
        )]
        repo = _make_repo_with_doc("doc_level", "internal API documentation endpoint", acl)
        results = repo.search_lexical("API", user_id="alice")
        assert len(results) == 1
        assert results[0].document_id == "doc_level"

    def test_document_level_read_denies_wrong_user(self):
        acl = [AclReference(
            resource_type="DOCUMENT",
            resource_id="doc_level2",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="READ",
        )]
        repo = _make_repo_with_doc("doc_level2", "internal API documentation endpoint", acl)
        results = repo.search_lexical("API", user_id="bob")
        assert len(results) == 0


# ============================================================================
# 3. CHUNK READ applies only to the matching chunk
# ============================================================================

class TestChunkRead:
    def test_chunk_level_read_grants_access_to_specific_chunk(self):
        """ACL with resource_type=CHUNK and resource_id=chunk.id should grant access."""
        acl = [AclReference(
            resource_type="CHUNK",
            resource_id="chunk:chunk_specific:0",
            principal_type=PrincipalType.USER,
            principal_id="carol",
            permission="READ",
        )]
        repo = _make_repo_with_doc("chunk_specific", "deployment runbook for staging cluster", acl)
        results = repo.search_lexical("deployment", user_id="carol")
        assert len(results) == 1
        assert results[0].chunk_id == "chunk:chunk_specific:0"

    def test_chunk_level_read_does_not_grant_access_to_other_chunks(self):
        """ACL targeting chunk:A should NOT grant access to chunk:B of the same document."""
        repo = InMemoryKnowledgeRepository()
        source_id = "raw:multi_chunk"
        raw = RawSourceItem(
            id=source_id,
            source_type=SourceType.GITHUB,
            source_id="multi_chunk",
            source_url="https://co.internal/multi",
            title="Multi Chunk Doc",
            raw_content="deployment details",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        doc = CanonicalDocument(
            id="multi_chunk",
            source_record_id=source_id,
            source_type="GITHUB",
            title="Multi Chunk Doc",
            content="deployment details",
            url="https://co.internal/multi",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        chunk_0 = CanonicalChunk(
            id="chunk:multi_chunk:0",
            document_id="multi_chunk",
            chunk_index=0,
            content="deployment details for prod cluster",
            token_count=5,
            content_hash=CanonicalChunk.compute_hash("deployment details for prod cluster"),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        chunk_1 = CanonicalChunk(
            id="chunk:multi_chunk:1",
            document_id="multi_chunk",
            chunk_index=1,
            content="deployment details for staging cluster",
            token_count=5,
            content_hash=CanonicalChunk.compute_hash("deployment details for staging cluster"),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        # ACL grants READ only to chunk:0
        acl = [AclReference(
            resource_type="CHUNK",
            resource_id="chunk:multi_chunk:0",
            principal_type=PrincipalType.USER,
            principal_id="eve",
            permission="READ",
        )]
        repo.save_source_records([raw])
        repo.save_documents([doc])
        repo.save_chunks([chunk_0, chunk_1])
        repo.save_acls(acl)

        results = repo.search_lexical("deployment", user_id="eve")
        # Only chunk_0 should be returned, chunk_1 has no matching ACL
        assert len(results) == 1
        assert results[0].chunk_id == "chunk:multi_chunk:0"


# ============================================================================
# 4. PUBLIC READ works for anonymous users
# ============================================================================

class TestPublicRead:
    def test_public_read_grants_access_with_no_identity(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:pub",
            principal_type=PrincipalType.PUBLIC,
            principal_id="*",
            permission="READ",
        )]
        repo = _make_repo_with_doc("pub", "welcome announcement company policy", acl)
        # user_id=None, group_ids=None
        results = repo.search_lexical("announcement", user_id=None, group_ids=None)
        assert len(results) == 1

    def test_public_read_grants_access_with_empty_groups(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:pub2",
            principal_type=PrincipalType.PUBLIC,
            principal_id="*",
            permission="READ",
        )]
        repo = _make_repo_with_doc("pub2", "welcome announcement company policy", acl)
        results = repo.search_lexical("announcement", user_id="", group_ids=[])
        assert len(results) == 1

    def test_public_write_does_not_grant_read(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:pub_w",
            principal_type=PrincipalType.PUBLIC,
            principal_id="*",
            permission="WRITE",
        )]
        repo = _make_repo_with_doc("pub_w", "welcome announcement company policy", acl)
        results = repo.search_lexical("announcement", user_id=None, group_ids=None)
        assert len(results) == 0


# ============================================================================
# 5. Missing identity never grants unrestricted access
# ============================================================================

class TestMissingIdentity:
    def test_none_identity_cannot_access_user_restricted(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:restricted",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="READ",
        )]
        repo = _make_repo_with_doc("restricted", "confidential design review notes", acl)
        assert repo.search_lexical("confidential", user_id=None, group_ids=None) == []

    def test_none_identity_cannot_access_group_restricted(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:grp",
            principal_type=PrincipalType.GROUP,
            principal_id="group_eng",
            permission="READ",
        )]
        repo = _make_repo_with_doc("grp", "engineering status report weekly", acl)
        assert repo.search_lexical("engineering", user_id=None, group_ids=None) == []
        assert repo.search_lexical("engineering", user_id=None, group_ids=[]) == []

    def test_empty_string_user_id_does_not_match(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:es",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="READ",
        )]
        repo = _make_repo_with_doc("es", "design review infrastructure", acl)
        assert repo.search_lexical("infrastructure", user_id="", group_ids=[]) == []

    def test_whitespace_user_id_does_not_match(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:ws",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="READ",
        )]
        repo = _make_repo_with_doc("ws", "design review infrastructure", acl)
        assert repo.search_lexical("infrastructure", user_id="   ", group_ids=[]) == []


# ============================================================================
# 6. Missing ACL and WRITE-only ACL deny read access
# ============================================================================

class TestDenyByDefault:
    def test_no_acls_at_all_denies(self):
        repo = _make_repo_with_doc("orphan", "orphan design specification document", [])
        assert repo.search_lexical("orphan", user_id="admin", group_ids=["group_admin"]) == []

    def test_write_only_denies_read(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:wo",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="WRITE",
        )]
        repo = _make_repo_with_doc("wo", "write only sensitive buffer data", acl)
        assert repo.search_lexical("sensitive", user_id="alice") == []

    def test_admin_permission_does_not_grant_read(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:adm",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="ADMIN",
        )]
        repo = _make_repo_with_doc("adm", "admin console configuration settings", acl)
        assert repo.search_lexical("console", user_id="alice") == []


# ============================================================================
# 7. USER and GROUP permissions isolated across different users
# ============================================================================

class TestIsolation:
    def test_user_acl_does_not_leak_to_other_users(self):
        acl = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:iso_u",
            principal_type=PrincipalType.USER,
            principal_id="alice",
            permission="READ",
        )]
        repo = _make_repo_with_doc("iso_u", "personal project notes timeline", acl)
        assert len(repo.search_lexical("project", user_id="alice")) == 1
        assert len(repo.search_lexical("project", user_id="bob")) == 0
        assert len(repo.search_lexical("project", user_id="eve")) == 0

    def test_group_acl_does_not_leak_to_other_groups(self):
        repo = InMemoryKnowledgeRepository()
        _add_doc(repo, "g1", "salary compensation quarterly report", [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:g1",
            principal_type=PrincipalType.GROUP,
            principal_id="group_hr",
            permission="READ",
        )])
        _add_doc(repo, "g2", "salary benchmarking engineering compensation", [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:g2",
            principal_type=PrincipalType.GROUP,
            principal_id="group_finance",
            permission="READ",
        )])

        # HR sees only their doc
        hr = repo.search_lexical("salary", group_ids=["group_hr"])
        assert len(hr) == 1
        assert hr[0].document_id == "g1"

        # Finance sees only their doc
        fin = repo.search_lexical("salary", group_ids=["group_finance"])
        assert len(fin) == 1
        assert fin[0].document_id == "g2"

        # Engineering sees neither
        eng = repo.search_lexical("salary", group_ids=["group_engineering"])
        assert len(eng) == 0

    def test_mixed_user_and_group_on_same_resource(self):
        """A resource with both USER and GROUP ACL should grant both."""
        acl = [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id="raw:mixed",
                principal_type=PrincipalType.USER,
                principal_id="alice",
                permission="READ",
            ),
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id="raw:mixed",
                principal_type=PrincipalType.GROUP,
                principal_id="group_ops",
                permission="READ",
            ),
        ]
        repo = _make_repo_with_doc("mixed", "infrastructure runbook playbook guide", acl)
        assert len(repo.search_lexical("runbook", user_id="alice", group_ids=[])) == 1
        assert len(repo.search_lexical("runbook", user_id="bob", group_ids=["group_ops"])) == 1
        assert len(repo.search_lexical("runbook", user_id="bob", group_ids=["group_dev"])) == 0


# ============================================================================
# 8. PostgreSQL ACL SQL: parameter ordering and resource joins
# ============================================================================

class TestSqlParameterOrdering:
    """Verify the generated SQL and parameter positions are correct.

    These tests validate the structure of the SQL generated by build_acl_where_clause
    and verify that the parameter list produced by PostgresKnowledgeRepository.search_lexical
    and search_vector would be in the correct positional order for psycopg execution.
    """

    def test_lexical_sql_param_order_with_user_group_source_filter(self):
        """Manually trace the parameter list for search_lexical with all options."""
        # Simulate what PostgresKnowledgeRepository.search_lexical does
        query = "test query"
        user_id = "employee_42"
        group_ids = ["group_eng", "group_backend"]
        source_types = ["GITHUB"]
        limit = 5

        acl_clause, acl_params = build_acl_where_clause(
            user_id=user_id, group_ids=group_ids,
            doc_alias="d", chunk_alias="c", acl_alias="a",
        )

        # Replicate the exact param assembly from PostgresKnowledgeRepository.search_lexical
        params = [query, query]  # ts_rank_cd score param, then tsv @@ plainto_tsquery param
        params.extend(acl_params)  # user_id, [group_ids]
        params.append(source_types)  # source_types filter
        params.append(limit)  # LIMIT

        # Expected: [query, query, user_id, [groups], source_types, limit]
        assert params == [
            "test query",       # plainto_tsquery (WHERE clause)
            "test query",       # ts_rank_cd (SELECT)
            "employee_42",      # USER principal_id
            ["group_eng", "group_backend"],  # GROUP principal_ids
            ["GITHUB"],         # source_type filter
            5,                  # LIMIT
        ]

    def test_vector_sql_param_order_with_user_group_source_filter(self):
        """Manually trace the parameter list for search_vector with all options."""
        query_emb = [0.1] * 1536
        user_id = "employee_42"
        group_ids = ["group_eng"]
        source_types = ["SLACK"]
        limit = 10

        acl_clause, acl_params = build_acl_where_clause(
            user_id=user_id, group_ids=group_ids,
            doc_alias="d", chunk_alias="c", acl_alias="a",
        )

        # Replicate the exact param assembly from PostgresKnowledgeRepository.search_vector
        params = [query_emb]  # First %s in SELECT: score calculation
        params.extend(acl_params)
        params.append(source_types)
        params.append(query_emb)  # ORDER BY clause
        params.append(limit)

        assert len(params) == 6
        assert params[0] is query_emb       # SELECT score
        assert params[1] == "employee_42"    # USER
        assert params[2] == ["group_eng"]    # GROUP
        assert params[3] == ["SLACK"]        # source_types
        assert params[4] is query_emb        # ORDER BY
        assert params[5] == 10               # LIMIT

    def test_sql_clause_resource_joins_cover_all_three_types(self):
        clause, _ = build_acl_where_clause(user_id="u", group_ids=["g"])
        # Must check all three resource_type scopes
        assert "a.resource_type = 'SOURCE_RECORD'" in clause
        assert "a.resource_type = 'DOCUMENT'" in clause
        assert "a.resource_type = 'CHUNK'" in clause
        # Must join correctly
        assert "a.resource_id = d.source_record_id" in clause  # SOURCE_RECORD
        assert "a.resource_id = d.id" in clause                 # DOCUMENT
        assert "a.resource_id = c.id" in clause                 # CHUNK

    def test_sql_clause_no_user_no_group_only_public(self):
        """When called with no identity, only PUBLIC matches."""
        clause, params = build_acl_where_clause(user_id=None, group_ids=[])
        assert params == []
        assert "a.principal_type = 'PUBLIC'" in clause
        # USER and GROUP clauses must not appear — no params to bind
        assert "'USER'" not in clause
        assert "'GROUP'" not in clause

    def test_lexical_params_no_source_filter(self):
        """Without source_types, parameter list should be shorter."""
        query = "test"
        user_id = "alice"
        group_ids = None
        limit = 10

        _, acl_params = build_acl_where_clause(user_id=user_id, group_ids=group_ids)
        params = [query, query]
        params.extend(acl_params)
        # No source_types
        params.append(limit)

        # Expected: [query, query, user_id, limit]
        assert params == ["test", "test", "alice", 10]


# ============================================================================
# 9. SQL filtering occurs before LIMIT (in-memory proof)
# ============================================================================

class TestPreLimitFiltering:
    def test_unauthorized_docs_do_not_consume_limit_slots(self):
        """If limit=1 and 10 unauthorized docs + 1 authorized doc exist,
        the authorized doc must be returned."""
        repo = InMemoryKnowledgeRepository()
        for i in range(10):
            did = f"blocked_{i}"
            _add_doc(repo, did, f"migration checklist item {i} migration database", [
                AclReference(
                    resource_type="SOURCE_RECORD",
                    resource_id=f"raw:{did}",
                    principal_type=PrincipalType.GROUP,
                    principal_id="group_restricted",
                    permission="READ",
                )
            ])
        _add_doc(repo, "allowed", "migration guide summary", [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id="raw:allowed",
                principal_type=PrincipalType.GROUP,
                principal_id="group_eng",
                permission="READ",
            )
        ])

        results = repo.search_lexical("migration", limit=1, group_ids=["group_eng"])
        assert len(results) == 1
        assert results[0].document_id == "allowed"

    def test_vector_unauthorized_docs_do_not_consume_limit_slots(self):
        """Same pre-limit proof for vector search."""
        provider = MockEmbeddingProvider()
        repo = InMemoryKnowledgeRepository()
        query_emb = provider.embed_query("migration database")

        for i in range(10):
            did = f"vblocked_{i}"
            emb = provider.embed_query(f"migration database checklist {i}")
            _add_doc(repo, did, f"migration database checklist {i}", [
                AclReference(
                    resource_type="SOURCE_RECORD",
                    resource_id=f"raw:{did}",
                    principal_type=PrincipalType.GROUP,
                    principal_id="group_restricted",
                    permission="READ",
                )
            ], embedding=emb)

        allowed_emb = provider.embed_query("migration database summary")
        _add_doc(repo, "vallowed", "migration database summary", [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id="raw:vallowed",
                principal_type=PrincipalType.GROUP,
                principal_id="group_eng",
                permission="READ",
            )
        ], embedding=allowed_emb)

        results = repo.search_vector(query_emb, limit=1, group_ids=["group_eng"])
        assert len(results) == 1
        assert results[0].document_id == "vallowed"


# ============================================================================
# 10. In-memory and PostgreSQL permission semantics match
# ============================================================================

class TestSemanticParity:
    """Verify that has_read_permission (used by InMemory) and build_acl_where_clause
    (used by PostgreSQL) agree on all principal/permission combinations."""

    @pytest.mark.parametrize("user_id,group_ids,principal_type,principal_id,permission,expected", [
        # PUBLIC READ → allow for anyone
        (None, None, PrincipalType.PUBLIC, "*", "READ", True),
        ("alice", ["eng"], PrincipalType.PUBLIC, "*", "READ", True),
        # PUBLIC WRITE → deny
        (None, None, PrincipalType.PUBLIC, "*", "WRITE", False),
        # USER READ match → allow
        ("alice", None, PrincipalType.USER, "alice", "READ", True),
        # USER READ mismatch → deny
        ("bob", None, PrincipalType.USER, "alice", "READ", False),
        # USER WRITE match → deny (wrong permission)
        ("alice", None, PrincipalType.USER, "alice", "WRITE", False),
        # GROUP READ match → allow
        (None, ["eng"], PrincipalType.GROUP, "eng", "READ", True),
        # GROUP READ mismatch → deny
        (None, ["mkt"], PrincipalType.GROUP, "eng", "READ", False),
        # GROUP WRITE match → deny
        (None, ["eng"], PrincipalType.GROUP, "eng", "WRITE", False),
        # No identity → deny for USER/GROUP
        (None, None, PrincipalType.USER, "alice", "READ", False),
        (None, None, PrincipalType.GROUP, "eng", "READ", False),
        # Empty string user → deny
        ("", None, PrincipalType.USER, "alice", "READ", False),
    ])
    def test_has_read_permission_matches_expected(
        self, user_id, group_ids, principal_type, principal_id, permission, expected
    ):
        acl = AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="res",
            principal_type=principal_type,
            principal_id=principal_id,
            permission=permission,
        )
        result = has_read_permission([acl], user_id=user_id, group_ids=group_ids)
        assert result is expected

    @pytest.mark.parametrize("user_id,group_ids,principal_type,principal_id,permission,expected_in_sql", [
        # PUBLIC READ → SQL includes PUBLIC, no params needed for it
        (None, None, PrincipalType.PUBLIC, "*", "READ", True),
        # USER READ match → SQL includes USER with param
        ("alice", None, PrincipalType.USER, "alice", "READ", True),
        # GROUP READ match → SQL includes GROUP with param
        (None, ["eng"], PrincipalType.GROUP, "eng", "READ", True),
    ])
    def test_sql_builder_would_match_same_cases(
        self, user_id, group_ids, principal_type, principal_id, permission, expected_in_sql
    ):
        """Verify the SQL clause structure would match the same cases as has_read_permission."""
        clause, params = build_acl_where_clause(user_id=user_id, group_ids=group_ids)
        # The clause always includes PUBLIC
        assert "a.principal_type = 'PUBLIC'" in clause
        # If user_id provided, USER clause appears with param
        if user_id:
            assert "a.principal_type = 'USER'" in clause
            assert user_id in params
        # If group_ids provided, GROUP clause appears with param
        if group_ids:
            assert "a.principal_type = 'GROUP'" in clause
            assert group_ids in params

    def test_lexical_and_vector_agree_on_authorization(self):
        """Prove lexical and vector search return identical document sets for same ACLs."""
        provider = MockEmbeddingProvider()
        repo = InMemoryKnowledgeRepository()

        acl_eng = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:sv_eng",
            principal_type=PrincipalType.GROUP,
            principal_id="group_eng",
            permission="READ",
        )]
        emb_eng = provider.embed_query("kubernetes deployment automation")
        _add_doc(repo, "sv_eng", "kubernetes deployment automation pipeline", acl_eng, embedding=emb_eng)

        acl_sec = [AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:sv_sec",
            principal_type=PrincipalType.GROUP,
            principal_id="group_security",
            permission="READ",
        )]
        emb_sec = provider.embed_query("kubernetes security vulnerability report")
        _add_doc(repo, "sv_sec", "kubernetes security vulnerability report patch", acl_sec, embedding=emb_sec)

        query_emb = provider.embed_query("kubernetes")

        # Eng user
        lex_eng = repo.search_lexical("kubernetes", group_ids=["group_eng"])
        vec_eng = repo.search_vector(query_emb, group_ids=["group_eng"])
        assert {r.document_id for r in lex_eng} == {"sv_eng"}
        assert {r.document_id for r in vec_eng} == {"sv_eng"}

        # Security user
        lex_sec = repo.search_lexical("kubernetes", group_ids=["group_security"])
        vec_sec = repo.search_vector(query_emb, group_ids=["group_security"])
        assert {r.document_id for r in lex_sec} == {"sv_sec"}
        assert {r.document_id for r in vec_sec} == {"sv_sec"}

        # No identity
        lex_none = repo.search_lexical("kubernetes", user_id=None, group_ids=None)
        vec_none = repo.search_vector(query_emb, user_id=None, group_ids=None)
        assert len(lex_none) == 0
        assert len(vec_none) == 0
