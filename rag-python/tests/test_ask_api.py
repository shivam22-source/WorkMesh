"""Focused integration tests for internal RAG ask API (/internal/v1/rag/ask)."""

import pytest
from fastapi.testclient import TestClient

from app.api.internal_rag import get_grounded_rag_service
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever


@pytest.fixture
def populated_ask_service() -> GroundedRagService:
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

    retriever = HybridRetriever(repository=repo)
    return GroundedRagService(retriever=retriever)


@pytest.fixture
def client(populated_ask_service: GroundedRagService) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_grounded_rag_service] = lambda: populated_ask_service
    return TestClient(app)


def test_ask_api_returns_grounded_answer_and_citations(client: TestClient):
    """POST /internal/v1/rag/ask returns 200 with grounded answer and citations."""
    response = client.post(
        "/internal/v1/rag/ask",
        json={
            "question": "why did DC-8692 change the validation flow?",
            "userId": "employee_42",
            "groupIds": ["group_engineering", "group_backend"],
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "ANSWERED"
    assert body["confidence"] == "MEDIUM"
    assert body["question"] == "why did DC-8692 change the validation flow?"
    assert len(body["answer"]) > 0
    assert "[1]" in body["answer"]

    assert len(body["citations"]) > 0
    top = body["citations"][0]
    for key in ["sourceType", "title", "url", "snippet"]:
        assert key in top
        assert top[key] != ""


def test_ask_api_source_filtering_slack(client: TestClient):
    """POST /internal/v1/rag/ask with sourceTypes filter restricts citations."""
    response = client.post(
        "/internal/v1/rag/ask",
        json={
            "question": "validation DC-8692",
            "userId": "employee_42",
            "groupIds": ["group_engineering"],
            "sourceTypes": ["SLACK"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ANSWERED"
    assert all(c["sourceType"] == "SLACK" for c in body["citations"])


def test_ask_api_missing_required_fields_rejected(client: TestClient):
    """Missing question or userId returns 422."""
    res_no_q = client.post("/internal/v1/rag/ask", json={"userId": "u1", "groupIds": []})
    assert res_no_q.status_code == 422

    res_no_user = client.post("/internal/v1/rag/ask", json={"question": "q"})
    assert res_no_user.status_code == 422


def test_ask_api_unknown_field_rejected(client: TestClient):
    """extra='forbid' rejects payload with unknown fields."""
    res = client.post(
        "/internal/v1/rag/ask",
        json={
            "question": "why validation?",
            "userId": "u1",
            "groupIds": [],
            "unknownParam": "unexpected",
        },
    )
    assert res.status_code == 422
