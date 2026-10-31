"""Focused unit tests for VectorRetriever covering vector matching, cosine ranking, and edge cases."""

import math
from unittest.mock import MagicMock
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
    return MockEmbeddingProvider(dimension=1536)


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
    mock_provider.dimension = 1536
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
    zero_vec = [0.0] * 1536
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
        embedding=[0.0] * 1536,
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

    # Setup mock return row
    mock_cursor.fetchall.return_value = [
        ("chunk:1", "doc:1", "GITHUB", "PR Title", "Fix payment verification", "https://github.com/...", "dev", 0.88),
    ]

    test_vector = [0.05] * 1536
    results = repo.search_vector(test_vector, limit=5, source_types=["GITHUB"])

    assert len(results) == 1
    assert results[0].chunk_id == "chunk:1"
    assert results[0].score == 0.88

    # Verify SQL query used pgvector <=> cosine distance and excluded zero vectors
    executed_sql, executed_params = mock_cursor.execute.call_args[0]
    assert "c.embedding <=>" in executed_sql
    assert "(- (c.embedding <#> c.embedding)) > 0" in executed_sql
    assert "d.source_type = ANY(%s)" in executed_sql
    assert "ORDER BY c.embedding <=> %s ASC" in executed_sql
    assert executed_params == (test_vector, ["GITHUB"], test_vector, 5)
