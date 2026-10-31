"""Focused integration tests for internal RAG search API (/internal/v1/rag/search)."""

from unittest.mock import MagicMock
from fastapi.testclient import TestClient
import pytest

from app.api.internal_rag import get_hybrid_retriever
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import DatabaseUnavailableError, InMemoryKnowledgeRepository
from app.main import create_app
from app.retrieval.hybrid import HybridRetriever


@pytest.fixture
def populated_retriever() -> HybridRetriever:
    """Pre-populates an in-memory repository with synthetic GitHub and Slack fixtures."""
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

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

    return HybridRetriever(repository=repo)


@pytest.fixture
def client(populated_retriever: HybridRetriever) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_hybrid_retriever] = lambda: populated_retriever
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Populated Search and Mixed Results
# ---------------------------------------------------------------------------

def test_search_api_returns_populated_results_with_mixed_sources(client: TestClient):
    """Querying ticket DC-8692 returns 200 with both GitHub and Slack results."""
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "DC-8692",
            "userId": "employee_42",
            "groupIds": ["group_engineering", "group_backend"],
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ok"
    assert body["query"] == "DC-8692"
    assert body["totalResults"] > 0
    assert len(body["results"]) == body["totalResults"]

    # Verify both GITHUB and SLACK source types appear
    source_types = {r["sourceType"] for r in body["results"]}
    assert "GITHUB" in source_types
    assert "SLACK" in source_types

    # Verify camelCase contract fields
    top = body["results"][0]
    for key in ["chunkId", "documentId", "sourceType", "title", "snippet", "sourceUrl", "score"]:
        assert key in top
    assert top["score"] > 0


# ---------------------------------------------------------------------------
# 2. Source-Type Filtering
# ---------------------------------------------------------------------------

def test_search_api_source_filtering_slack(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "validation",
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
            "sourceTypes": ["SLACK"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["totalResults"] > 0
    assert all(r["sourceType"] == "SLACK" for r in body["results"])


def test_search_api_source_filtering_github(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "validation",
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
            "sourceTypes": ["GITHUB"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["totalResults"] > 0
    assert all(r["sourceType"] == "GITHUB" for r in body["results"])


# ---------------------------------------------------------------------------
# 3. Limit Enforcement
# ---------------------------------------------------------------------------

def test_search_api_limit_enforced(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "validation",
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
            "limit": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 2
    assert body["totalResults"] == 2


# ---------------------------------------------------------------------------
# 4. Zero Matches Handling (200 with Empty List)
# ---------------------------------------------------------------------------

def test_search_api_zero_matches_returns_200_empty():
    """An empty repository returns 200 with totalResults: 0 and results: []."""
    app = create_app()
    empty_retriever = HybridRetriever(repository=InMemoryKnowledgeRepository())
    app.dependency_overrides[get_hybrid_retriever] = lambda: empty_retriever

    with TestClient(app) as test_client:
        response = test_client.post(
            "/internal/v1/rag/search",
            json={
                "query": "nonexistent_token_xyz_99999",
                "userId": "employee_42",
                "groupIds": ["group_engineering"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["totalResults"] == 0
    assert body["results"] == []


# ---------------------------------------------------------------------------
# 5. Database Unavailable Handling (503 Service Unavailable)
# ---------------------------------------------------------------------------

def test_search_api_database_unavailable_returns_503():
    """When PostgreSQL is down, the endpoint must return 503 instead of 200 with empty results."""
    mock_retriever = MagicMock(spec=HybridRetriever)
    mock_retriever.search.side_effect = DatabaseUnavailableError("Connection refused to postgresql://localhost:5432/knowledge")

    app = create_app()
    app.dependency_overrides[get_hybrid_retriever] = lambda: mock_retriever

    with TestClient(app) as test_client:
        response = test_client.post(
            "/internal/v1/rag/search",
            json={
                "query": "validation",
                "userId": "employee_42",
                "groupIds": ["group_engineering"],
            },
        )

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == 503
    assert body["error"] == "Service Unavailable"
    assert body["message"] == "database service is unavailable"


# ---------------------------------------------------------------------------
# 6. Request Validation (422 Unprocessable Entity)
# ---------------------------------------------------------------------------

def test_search_api_missing_query_returns_422(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
        },
    )
    assert response.status_code == 422


def test_search_api_empty_query_returns_422(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "",
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
        },
    )
    assert response.status_code == 422


def test_search_api_missing_user_id_returns_422(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "validation",
            "groupIds": ["group_engineering"],
        },
    )
    assert response.status_code == 422


def test_search_api_invalid_limit_returns_422(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "validation",
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
            "limit": 0,
        },
    )
    assert response.status_code == 422


def test_search_api_unexpected_field_returns_422(client: TestClient):
    response = client.post(
        "/internal/v1/rag/search",
        json={
            "query": "validation",
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
            "unexpected_field": "disallowed",
        },
    )
    assert response.status_code == 422
