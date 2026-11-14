"""Focused unit tests for LexicalRetriever covering identifiers, keywords, ranking, and fallbacks."""

from unittest.mock import MagicMock

import pytest

from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import (
    InMemoryKnowledgeRepository,
    PostgresKnowledgeRepository,
)
from app.retrieval.lexical import LexicalRetriever


@pytest.fixture
def populated_repository() -> InMemoryKnowledgeRepository:
    """Pre-populates an in-memory repository with synthetic GitHub and Slack fixtures."""
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    # 1. Ingest GitHub fixture
    github_connector = GitHubFixtureAdapter()
    github_pipeline = IngestionPipeline(
        connector=github_connector,
        repository=repo,
        embedding_provider=embeddings,
    )
    github_pipeline.run()

    # 2. Ingest Slack fixture
    slack_connector = SlackFixtureAdapter()
    slack_pipeline = IngestionPipeline(
        connector=slack_connector,
        repository=repo,
        embedding_provider=embeddings,
    )
    slack_pipeline.run()

    return repo


@pytest.fixture
def retriever(populated_repository: InMemoryKnowledgeRepository) -> LexicalRetriever:
    return LexicalRetriever(
        populated_repository,
        default_user_id="employee_42",
        default_group_ids=["group_engineering", "group_backend"],
    )


# ---------------------------------------------------------------------------
# 1. Exact Identifier Retrieval Tests
# ---------------------------------------------------------------------------

def test_exact_ticket_id_retrieval(retriever: LexicalRetriever):
    """Querying Jira ticket DC-8692 returns both GitHub and Slack records referencing it."""
    results = retriever.search("DC-8692")
    assert len(results) > 0

    sources = {r.source_type for r in results}
    assert "GITHUB" in sources
    assert "SLACK" in sources

    # Check top result
    top = results[0]
    assert top.score > 0
    assert "DC-8692" in top.snippet or "DC-8692" in top.title


def test_exact_commit_hash_retrieval(retriever: LexicalRetriever):
    """Querying commit hash 8af2d1e94b2a8d3e returns the commit chunk."""
    results = retriever.search("8af2d1e94b2a8d3e")
    assert len(results) >= 1
    top = results[0]
    assert top.source_type == "GITHUB"
    assert "8af2d1e9" in top.snippet or "8af2d1e9" in top.title
    assert top.score > 0


# ---------------------------------------------------------------------------
# 2. Technical Keyword Retrieval Tests
# ---------------------------------------------------------------------------

def test_technical_keyword_retrieval(retriever: LexicalRetriever):
    """Querying NullPointerException returns payment validation chunk."""
    results = retriever.search("NullPointerException")
    assert len(results) >= 1
    top = results[0]
    assert "NullPointerException" in top.snippet or "null" in top.snippet.lower()
    assert top.score > 0


def test_service_name_keyword_retrieval(retriever: LexicalRetriever):
    """Querying PaymentValidationService matches relevant PR chunk."""
    results = retriever.search("PaymentValidationService")
    assert len(results) >= 1
    assert any("PaymentValidationService" in r.snippet for r in results)


# ---------------------------------------------------------------------------
# 3. Multiple Matches and Score Ordering Tests
# ---------------------------------------------------------------------------

def test_multiple_matches_ranked_descending(retriever: LexicalRetriever):
    """Common keyword 'validation' matches multiple chunks, ranked by score descending."""
    results = retriever.search("validation", limit=10)
    assert len(results) >= 2

    # Verify monotonic descending score order
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_limit_parameter_is_respected(retriever: LexicalRetriever):
    results = retriever.search("validation", limit=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 4. Source Filtering Tests
# ---------------------------------------------------------------------------

def test_filter_by_slack_source(retriever: LexicalRetriever):
    results = retriever.search("validation", source_types=["SLACK"])
    assert len(results) > 0
    assert all(r.source_type == "SLACK" for r in results)


def test_filter_by_github_source(retriever: LexicalRetriever):
    results = retriever.search("validation", source_types=["GITHUB"])
    assert len(results) > 0
    assert all(r.source_type == "GITHUB" for r in results)


# ---------------------------------------------------------------------------
# 5. Empty and No-Result Queries
# ---------------------------------------------------------------------------

def test_empty_and_whitespace_queries(retriever: LexicalRetriever):
    assert retriever.search("") == []
    assert retriever.search("   ") == []
    assert retriever.search("\t\n") == []


def test_no_result_query(retriever: LexicalRetriever):
    results = retriever.search("xyz_nonexistent_token_99999")
    assert results == []


# ---------------------------------------------------------------------------
# 6. PostgresKnowledgeRepository Full-Text Parameterized SQL Test
# ---------------------------------------------------------------------------

def test_postgres_search_lexical_sql_structure():
    """Verify PostgresKnowledgeRepository generates parameterized ts_rank_cd SQL without error."""
    repo = PostgresKnowledgeRepository("postgresql://mock:mock@localhost:5432/mock")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    repo._get_connection = MagicMock(return_value=mock_conn)
    mock_conn.__enter__.return_value = mock_conn

    # Setup mock return row
    mock_cursor.fetchall.return_value = [
        ("chunk:1", "doc:1", "GITHUB", "PR Title", "Fix NullPointerException in checkout", "https://github.com/...", "dev", 0.42),
    ]

    results = repo.search_lexical("NullPointerException", limit=5, source_types=["GITHUB"])

    assert len(results) == 1
    assert results[0].chunk_id == "chunk:1"
    assert results[0].score == 0.42

    # Verify SQL query used ts_rank_cd and fair OR semantics by default
    executed_sql, executed_params = mock_cursor.execute.call_args[0]
    assert "replace(plainto_tsquery('english', %s)::text, '&', '|')::tsquery" in executed_sql
    assert "d.source_type = ANY(%s)" in executed_sql
    assert executed_params == ("NullPointerException", "NullPointerException", "NullPointerException", "NullPointerException", ["GITHUB"], 5)

    # Verify strict AND semantics
    repo.search_lexical("NullPointerException", limit=5, source_types=["GITHUB"], semantics="and")
    executed_sql_and, executed_params_and = mock_cursor.execute.call_args[0]
    assert "ts_rank_cd(c.tsv, plainto_tsquery('english', %s))" in executed_sql_and
    assert "c.tsv @@ plainto_tsquery('english', %s)" in executed_sql_and
    assert executed_params_and == ("NullPointerException", "NullPointerException", ["GITHUB"], 5)
