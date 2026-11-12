"""Focused unit tests for VectorRetriever covering vector matching, cosine ranking, and edge cases."""

import math
from unittest.mock import MagicMock

import pgvector
import pytest

from app.chunking.models import CanonicalChunk
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import (
    InMemoryKnowledgeRepository,
    PostgresKnowledgeRepository,
)
from app.normalization.models import CanonicalDocument
from app.retrieval.vector import VectorRetriever


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    return MockEmbeddingProvider(dimension=384)


@pytest.fixture
def populated_repository(embedding_provider: MockEmbeddingProvider) -> InMemoryKnowledgeRepository:
    """Pre-populates an in-memory repository with synthetic GitHub and Slack fixtures."""
    repo = InMemoryKnowledgeRepository()

    # 1. Ingest GitHub fixture
    github_pipeline = IngestionPipeline(
        connector=GitHubFixtureAdapter(),
        repository=repo,
        embedding_provider=embedding_provider,
    )
    github_pipeline.run()

    # 2. Ingest Slack fixture
    slack_pipeline = IngestionPipeline(
        connector=SlackFixtureAdapter(),
        repository=repo,
        embedding_provider=embedding_provider,
    )
    slack_pipeline.run()

    return repo


@pytest.fixture
def retriever(
    populated_repository: InMemoryKnowledgeRepository,
    embedding_provider: MockEmbeddingProvider,
) -> VectorRetriever:
    return VectorRetriever(
        repository=populated_repository,
        embedding_provider=embedding_provider,
        default_user_id="employee_42",
        default_group_ids=["group_engineering", "group_backend"],
    )


# ---------------------------------------------------------------------------
# 1. Exact Vector Match & Similarity Score Tests
# ---------------------------------------------------------------------------

def test_exact_vector_match_returns_highest_rank(
    populated_repository: InMemoryKnowledgeRepository,
    retriever: VectorRetriever,
):
    """An exact matching vector returns the source chunk at rank #1 with score ~1.0."""
    target_chunk = next(iter(populated_repository.chunks.values()))
    assert target_chunk.embedding is not None

    results = retriever.search_by_vector(target_chunk.embedding, limit=5)
    assert len(results) > 0

    top = results[0]
    assert top.chunk_id == target_chunk.id
    # Score should be ~1.0 for identical vector
    assert math.isclose(top.score, 1.0, rel_tol=1e-3)


def test_similarity_score_ordering_is_descending(retriever: VectorRetriever):
    """Results must be ordered monotonically descending by cosine similarity."""
    results = retriever.search("payment validation checkout", limit=10)
    assert len(results) >= 2

    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    # Range is preserved within [-1.0, 1.0]
    assert all(-1.0 <= s <= 1.0 for s in scores)


# ---------------------------------------------------------------------------
# 2. Source-Type Filtering Tests
# ---------------------------------------------------------------------------

def test_filter_by_slack_source(retriever: VectorRetriever):
    results = retriever.search("payment error", source_types=["SLACK"])
    assert len(results) > 0
    assert all(r.source_type == "SLACK" for r in results)


def test_filter_by_github_source(retriever: VectorRetriever):
    results = retriever.search("payment error", source_types=["GITHUB"])
    assert len(results) > 0
    assert all(r.source_type == "GITHUB" for r in results)


# ---------------------------------------------------------------------------
# 3. Limit Enforcement
# ---------------------------------------------------------------------------

def test_limit_parameter_is_strictly_enforced(retriever: VectorRetriever):
    results = retriever.search("validation", limit=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 4. Empty and Whitespace Queries (No Provider Call)
# ---------------------------------------------------------------------------

def test_empty_query_returns_empty_without_calling_provider(
    populated_repository: InMemoryKnowledgeRepository,
):
    mock_provider = MagicMock()
    mock_provider.dimension = 384
    r = VectorRetriever(repository=populated_repository, embedding_provider=mock_provider)

    assert r.search("") == []
    assert r.search("   ") == []
    assert r.search("\t\n") == []

    # Embedding provider must not be called for empty/whitespace input
    mock_provider.embed_query.assert_not_called()
    mock_provider.embed_texts.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Zero Vectors and Exclusion Tests
# ---------------------------------------------------------------------------

def test_zero_query_vector_returns_empty(retriever: VectorRetriever):
    """A zero query vector has no direction and must return [] without division by zero."""
    zero_vec = [0.0] * 384
    assert retriever.search_by_vector(zero_vec) == []


def test_zero_chunk_vectors_are_excluded(
    populated_repository: InMemoryKnowledgeRepository,
    retriever: VectorRetriever,
    embedding_provider: MockEmbeddingProvider,
):
    """Chunks with zero vectors must be excluded from retrieval candidates."""
    zero_chunk = CanonicalChunk(
        id="chunk:zero:0",
        document_id="doc:zero",
        chunk_index=0,
        content="Zero vector chunk content",
        token_count=10,
        content_hash="zero_hash",
        embedding=[0.0] * 384,
    )
    populated_repository.chunks[zero_chunk.id] = zero_chunk
    populated_repository.documents["doc:zero"] = CanonicalDocument(
        id="doc:zero",
        source_record_id="rec:zero",
        source_type="GITHUB",
        title="Zero Document",
        content="Zero vector chunk content",
        author="dev",
        url="https://example.com",
    )

    sample_vec = embedding_provider.embed_query("any query")
    results = retriever.search_by_vector(sample_vec, limit=20)

    # Zero chunk must never appear in results
    result_ids = [r.chunk_id for r in results]
    assert "chunk:zero:0" not in result_ids


# ---------------------------------------------------------------------------
# 6. Dimension Validation Tests
# ---------------------------------------------------------------------------

def test_dimension_mismatch_raises_value_error(retriever: VectorRetriever):
    """Mismatched embedding dimensions must raise ValueError, not truncate or pad."""
    with pytest.raises(ValueError, match="dimension mismatch"):
        retriever.search_by_vector([0.1] * 512)

    with pytest.raises(ValueError, match="dimension mismatch"):
        retriever.search_by_vector([0.1] * 2048)


# ---------------------------------------------------------------------------
# 7. Empty Repository Test
# ---------------------------------------------------------------------------

def test_empty_repository_returns_empty_list(embedding_provider: MockEmbeddingProvider):
    empty_repo = InMemoryKnowledgeRepository()
    r = VectorRetriever(repository=empty_repo, embedding_provider=embedding_provider)
    assert r.search("hello") == []


# ---------------------------------------------------------------------------
# 8. PostgresKnowledgeRepository Vector SQL Parameterization Test
# ---------------------------------------------------------------------------

def test_postgres_search_vector_sql_structure():
    """Verify PostgresKnowledgeRepository generates parameterized pgvector SQL with <=> and norm check."""
    repo = PostgresKnowledgeRepository("postgresql://mock:mock@localhost:5432/mock")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    repo._get_connection = MagicMock(return_value=mock_conn)
    mock_conn.__enter__.return_value = mock_conn

    # Setup mock return rows (5 items so fast path fulfills the limit)
    mock_cursor.fetchall.return_value = [
        (f"chunk:{i}", f"doc:{i}", "GITHUB", f"PR Title {i}", "Content", "https://...", "dev", 0.88 - (i-1)*0.01)
        for i in range(1, 6)
    ]

    test_vector = [0.05] * 384
    results = repo.search_vector(test_vector, limit=5, source_types=["GITHUB"])

    assert len(results) == 5
    assert results[0].chunk_id == "chunk:1"
    assert results[0].score == 0.88

    # Verify SQL query used pgvector <=> cosine distance and candidate retrieval
    executed_sql, executed_params = mock_cursor.execute.call_args[0]
    assert "WITH candidates AS" in executed_sql
    assert "c.embedding <=>" in executed_sql
    assert "(- (c.embedding <#> c.embedding)) > 0" in executed_sql
    assert "d.source_type = ANY(%s)" in executed_sql
    assert "ORDER BY c.embedding <=> %s ASC" in executed_sql
    expected_vec = pgvector.Vector(test_vector)
    assert executed_params == (expected_vec, expected_vec, 100, ["GITHUB"], 5)
    mock_conn.transaction.assert_called_once()


def test_postgres_search_vector_fallback_for_low_access_user():
    """When fewer candidates survive ACL filtering than limit, exact fallback is invoked."""
    repo = PostgresKnowledgeRepository("postgresql://mock:mock@localhost:5432/mock")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    repo._get_connection = MagicMock(return_value=mock_conn)
    mock_conn.__enter__.return_value = mock_conn

    # First fetchall (from sql_fast) returns only 1 row (< limit of 5)
    # Second fetchall (from sql_fallback) returns 3 rows
    mock_cursor.fetchall.side_effect = [
        [("chunk:1", "doc:1", "GITHUB", "PR 1", "Content 1", "https://...", "dev", 0.90)],
        [
            ("chunk:1", "doc:1", "GITHUB", "PR 1", "Content 1", "https://...", "dev", 0.90),
            ("chunk:2", "doc:2", "GITHUB", "PR 2", "Content 2", "https://...", "dev", 0.85),
            ("chunk:3", "doc:3", "GITHUB", "PR 3", "Content 3", "https://...", "dev", 0.80),
        ],
    ]

    test_vector = [0.05] * 384
    results = repo.search_vector(test_vector, limit=5, source_types=["GITHUB"], user_id="low_access_user")

    assert len(results) == 3
    assert [r.chunk_id for r in results] == ["chunk:1", "chunk:2", "chunk:3"]

    # Verify fallback query was executed last
    fallback_sql, fallback_params = mock_cursor.execute.call_args[0]
    assert "FROM chunks c" in fallback_sql
    assert "JOIN documents d ON c.document_id = d.id" in fallback_sql
    assert "ORDER BY c.embedding <=> %s ASC" in fallback_sql
    expected_vec = pgvector.Vector(test_vector)
    # Param structure for fallback: [vec_param, acl_param, source_types, vec_param, limit]
    assert fallback_params[-2] == expected_vec
    assert fallback_params[-1] == 5


def test_low_access_user_gets_results_and_zero_acl_leakage(embedding_provider: MockEmbeddingProvider):
    """A low-access user (1% of corpus) retrieves their permitted chunks, never unauthorized ones."""
    from datetime import datetime, timezone

    from app.connectors.common.models import AclReference, PrincipalType

    repo = InMemoryKnowledgeRepository()

    # Ingest 100 documents (each with 1 chunk)
    # 99 docs restricted to 'group_finance'
    # 1 doc restricted to 'user_special' (1% access)
    for i in range(100):
        doc_id = f"doc_{i:03d}"
        source_id = f"raw_{doc_id}"
        is_special = (i == 42)

        doc = CanonicalDocument(
            id=doc_id,
            source_record_id=source_id,
            source_type="GITHUB",
            title=f"Secret Doc {doc_id}",
            content=f"Content for {doc_id} with sensitive keyword search",
            url=f"https://github.com/repo/{doc_id}",
            author="engineer",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        # Unique vector per document
        vec = [0.01 * (i % 50)] * 384
        chunk = CanonicalChunk(
            id=f"chunk_{i:03d}",
            document_id=doc_id,
            chunk_index=0,
            token_count=10,
            content_hash=f"hash_{i:03d}",
            content=f"Content for {doc_id}",
            embedding=vec,
            created_at=datetime.now(timezone.utc),
        )

        if is_special:
            acls = [AclReference(
                resource_type="DOCUMENT",
                resource_id=doc_id,
                principal_type=PrincipalType.USER,
                principal_id="user_special",
                permission="READ",
            )]
        else:
            acls = [AclReference(
                resource_type="DOCUMENT",
                resource_id=doc_id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_finance",
                permission="READ",
            )]

        repo.save_documents([doc])
        repo.save_chunks([chunk])
        repo.save_acls(acls)

    # 1. Low access user search
    query_vec = [0.01 * (42 % 50)] * 384
    results = repo.search_vector(query_vec, limit=5, user_id="user_special", group_ids=[])
    assert len(results) == 1
    assert results[0].chunk_id == "chunk_042"
    assert results[0].document_id == "doc_042"

    # 2. Verify NO unauthorized chunk is present
    for r in results:
        assert r.document_id == "doc_042"
        assert r.chunk_id == "chunk_042"

    # 3. Completely unauthorized user gets 0 results
    unauth_results = repo.search_vector(query_vec, limit=5, user_id="unauthorized_user", group_ids=[])
    assert len(unauth_results) == 0
