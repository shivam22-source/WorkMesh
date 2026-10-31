"""Focused unit tests for HybridRetriever covering RRF fusion, deduplication, tie handling, and filtering."""

import math
from unittest.mock import MagicMock
import pytest

from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.contracts.rag_search import RagSearchResultItem
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository
from app.retrieval.hybrid import DEFAULT_RRF_K, HybridRetriever, compute_rrf_score
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.vector import VectorRetriever


def _create_mock_item(chunk_id: str, title: str = "Doc", score: float = 1.0, source_type: str = "GITHUB") -> RagSearchResultItem:
    return RagSearchResultItem(
        chunk_id=chunk_id,
        document_id=f"doc:{chunk_id}",
        source_type=source_type,
        title=title,
        snippet=f"Snippet for {chunk_id}",
        source_url=f"https://example.com/{chunk_id}",
        score=score,
    )


# ---------------------------------------------------------------------------
# 1. Pure RRF Calculation Tests
# ---------------------------------------------------------------------------

def test_pure_rrf_score_calculation():
    k = DEFAULT_RRF_K  # 60

    # Rank 1 in lexical only: 1 / (60 + 1)
    score_lex_only = compute_rrf_score(lexical_rank=1, vector_rank=None, k=k)
    assert math.isclose(score_lex_only, 1.0 / 61.0, rel_tol=1e-6)

    # Rank 1 in vector only: 1 / (60 + 1)
    score_vec_only = compute_rrf_score(lexical_rank=None, vector_rank=1, k=k)
    assert math.isclose(score_vec_only, 1.0 / 61.0, rel_tol=1e-6)

    # Rank 1 in both: 1/61 + 1/61
    score_both = compute_rrf_score(lexical_rank=1, vector_rank=1, k=k)
    assert math.isclose(score_both, 2.0 / 61.0, rel_tol=1e-6)

    # Configurable k = 10
    score_custom_k = compute_rrf_score(lexical_rank=1, vector_rank=1, k=10)
    assert math.isclose(score_custom_k, 2.0 / 11.0, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 2. Results Appearing in Both vs Single Lists & Score-Based Ranking
# ---------------------------------------------------------------------------

def test_results_appearing_in_both_lists_outrank_equivalent_single_list():
    item_a = _create_mock_item("chunk:both")
    item_b = _create_mock_item("chunk:lex_only")
    item_c = _create_mock_item("chunk:vec_only")

    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)

    # chunk:both is rank 1 in both; chunk:lex_only is rank 2 in lexical; chunk:vec_only is rank 2 in vector
    mock_lex.search.return_value = [item_a, item_b]
    mock_vec.search.return_value = [item_a, item_c]

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("test query", limit=10)

    assert len(results) == 3
    assert results[0].chunk_id == "chunk:both"
    # Rank 1 in both: 2 / 61 ≈ 0.032787
    assert math.isclose(results[0].score, round(2.0 / 61.0, 6), rel_tol=1e-5)


def test_single_list_high_rank_outranks_dual_list_low_rank():
    """Verify sorting is strictly by RRF score descending.

    Rank 1 in single list (1/61 ≈ 0.016393) must outrank an item appearing
    at rank 100 in both lists (1/160 + 1/160 = 2/160 = 0.0125).
    """
    item_high_single = _create_mock_item("chunk:high_single")
    item_low_both = _create_mock_item("chunk:low_both")

    lex_list = [item_high_single] + [_create_mock_item(f"filler:lex:{i}") for i in range(2, 100)] + [item_low_both]
    vec_list = [_create_mock_item(f"filler:vec:{i}") for i in range(1, 100)] + [item_low_both]

    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = lex_list
    mock_vec.search.return_value = vec_list

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("test query", limit=10)

    # chunk:high_single (score ≈ 0.016393) must strictly outrank chunk:low_both (score = 0.0125)
    assert results[0].chunk_id == "chunk:high_single"
    assert results[0].score > 0.016


# ---------------------------------------------------------------------------
# 3. Deduplication and Metadata Preservation
# ---------------------------------------------------------------------------

def test_deduplication_by_chunk_id_preserves_lexical_snippet():
    item_lex = RagSearchResultItem(
        chunk_id="chunk:shared",
        document_id="doc:shared",
        source_type="GITHUB",
        title="Lexical PR Title",
        snippet="Lexical matched snippet with [keyword]",
        source_url="https://github.com/pull/1",
        score=0.9,
    )
    item_vec = RagSearchResultItem(
        chunk_id="chunk:shared",
        document_id="doc:shared",
        source_type="GITHUB",
        title="Lexical PR Title",
        snippet="Generic vector snippet",
        source_url="https://github.com/pull/1",
        score=0.75,
    )

    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = [item_lex]
    mock_vec.search.return_value = [item_vec]

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("keyword", limit=10)

    assert len(results) == 1
    assert results[0].chunk_id == "chunk:shared"
    # Lexical snippet is preserved
    assert results[0].snippet == "Lexical matched snippet with [keyword]"
    # Score is the RRF score, not lexical or cosine score
    assert math.isclose(results[0].score, round(2.0 / 61.0, 6), rel_tol=1e-5)


# ---------------------------------------------------------------------------
# 4. Tie-Breaking Handling
# ---------------------------------------------------------------------------

def test_tie_breaking_is_stable_and_deterministic():
    # Item A is rank 1 in lexical only (score 1/61)
    item_a = _create_mock_item("chunk:bbb", title="Item A")
    # Item B is rank 1 in vector only (score 1/61)
    item_b = _create_mock_item("chunk:aaa", title="Item B")

    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = [item_a]
    mock_vec.search.return_value = [item_b]

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("query", limit=10)

    assert len(results) == 2
    # Both have score 1/61 ≈ 0.016393
    assert math.isclose(results[0].score, results[1].score, rel_tol=1e-5)
    # Item with lexical rank is favored on tie-break before vector-only item
    assert results[0].chunk_id == "chunk:bbb"
    assert results[1].chunk_id == "chunk:aaa"


# ---------------------------------------------------------------------------
# 5. Metadata and Source-Type Filtering
# ---------------------------------------------------------------------------

def test_source_type_filter_is_passed_to_retrievers():
    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = [_create_mock_item("chunk:slack:1", source_type="SLACK")]
    mock_vec.search.return_value = [_create_mock_item("chunk:slack:2", source_type="SLACK")]

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("test", source_types=["SLACK"])

    # Verify retrievers received source_types filter
    mock_lex.search.assert_called_once()
    assert mock_lex.search.call_args[1]["source_types"] == ["SLACK"]
    mock_vec.search.assert_called_once()
    assert mock_vec.search.call_args[1]["source_types"] == ["SLACK"]

    assert len(results) == 2
    assert all(r.source_type == "SLACK" for r in results)


# ---------------------------------------------------------------------------
# 6. Empty Lists and Edge Cases
# ---------------------------------------------------------------------------

def test_empty_query_returns_empty_immediately():
    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)

    assert retriever.search("") == []
    assert retriever.search("   ") == []
    mock_lex.search.assert_not_called()
    mock_vec.search.assert_not_called()


def test_empty_lexical_list_returns_vector_candidates():
    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = []
    mock_vec.search.return_value = [_create_mock_item("chunk:vec:1")]

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("query")

    assert len(results) == 1
    assert results[0].chunk_id == "chunk:vec:1"
    assert math.isclose(results[0].score, round(1.0 / 61.0, 6), rel_tol=1e-5)


def test_empty_vector_list_returns_lexical_candidates():
    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = [_create_mock_item("chunk:lex:1")]
    mock_vec.search.return_value = []

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("query")

    assert len(results) == 1
    assert results[0].chunk_id == "chunk:lex:1"
    assert math.isclose(results[0].score, round(1.0 / 61.0, 6), rel_tol=1e-5)


def test_both_lists_empty_returns_empty():
    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = []
    mock_vec.search.return_value = []

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    assert retriever.search("nonexistent") == []


def test_limit_parameter_is_strictly_enforced():
    items = [_create_mock_item(f"chunk:{i}") for i in range(10)]
    mock_lex = MagicMock(spec=LexicalRetriever)
    mock_vec = MagicMock(spec=VectorRetriever)
    mock_lex.search.return_value = items
    mock_vec.search.return_value = items

    retriever = HybridRetriever(lexical_retriever=mock_lex, vector_retriever=mock_vec)
    results = retriever.search("query", limit=3)

    assert len(results) == 3


# ---------------------------------------------------------------------------
# 7. End-to-End Populated Repository Integration
# ---------------------------------------------------------------------------

def test_hybrid_retriever_with_populated_repository():
    """Verify HybridRetriever instantiated with repository runs end-to-end on ingested data."""
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    # Ingest fixtures
    IngestionPipeline(
        connector=GitHubFixtureAdapter(),
        repository=repo,
        embedding_provider=embeddings,
    ).run()
    IngestionPipeline(
        connector=SlackFixtureAdapter(),
        repository=repo,
        embedding_provider=embeddings,
    ).run()

    retriever = HybridRetriever(
        repository=repo,
        default_user_id="employee_42",
        default_group_ids=["group_engineering", "group_backend"],
    )

    # 1. Identifier query (DC-8692)
    results_id = retriever.search("DC-8692", limit=5)
    assert len(results_id) > 0
    # Top result should mention DC-8692
    assert "DC-8692" in results_id[0].snippet or "DC-8692" in results_id[0].title
    assert results_id[0].score > 0

    # 2. Keyword query
    results_kw = retriever.search("NullPointerException", limit=5)
    assert len(results_kw) > 0
    assert any("NullPointerException" in r.snippet or "null" in r.snippet.lower() for r in results_kw)

    # 3. Source filtering
    slack_results = retriever.search("validation", limit=10, source_types=["SLACK"])
    assert len(slack_results) > 0
    assert all(r.source_type == "SLACK" for r in slack_results)
