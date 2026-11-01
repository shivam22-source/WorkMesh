"""Contract tests for internal RAG endpoints.

These are the Python-side guard against drift. They assert the exact wire
shape that backend-java's records expect, so a rename on one side fails
a test on the other side instead of failing at runtime.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.internal_rag import get_hybrid_retriever
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.retrieval.hybrid import HybridRetriever

EXPECTED_HEALTH_RESPONSE_KEYS = {"status", "service", "contractVersion", "message"}
EXPECTED_SEARCH_RESPONSE_KEYS = {"status", "query", "totalResults", "results"}
EXPECTED_ASK_RESPONSE_KEYS = {"question", "answer", "citations", "confidence", "status", "latencyBreakdownMs"}
EXPECTED_CITATION_ITEM_KEYS = {"sourceType", "title", "url", "snippet"}


def _post_contract(client: TestClient) -> dict:
    response = client.post(
        "/internal/v1/rag/health",
        json={
            "requestedBy": "backend-java",
            "requestedAt": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 200
    return response.json()


def test_contract_response_matches_java_record() -> None:
    with TestClient(create_app()) as client:
        body = _post_contract(client)

    assert set(body.keys()) == EXPECTED_HEALTH_RESPONSE_KEYS
    assert body["status"] == "ok"
    assert body["service"] == "rag-python"
    assert body["contractVersion"] == "v1"
    assert body["message"] == "contract stub alive"


def test_missing_required_field_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/internal/v1/rag/health", json={"requestedBy": "backend-java"})

    assert response.status_code == 422


def test_unknown_field_is_rejected() -> None:
    """extra='forbid' stops a typo from being silently ignored."""
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/v1/rag/health",
            json={
                "requestedBy": "backend-java",
                "requestedAt": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
                "unexpected": "value",
            },
        )

    assert response.status_code == 422


def test_search_contract_response_matches_java_record() -> None:
    app = create_app()
    app.dependency_overrides[get_hybrid_retriever] = lambda: HybridRetriever(InMemoryKnowledgeRepository())
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/rag/search",
            json={
                "query": "why did we change validation",
                "userId": "employee_42",
                "groupIds": ["group_engineering", "group_backend"],
                "limit": 10,
                "sourceTypes": ["GITHUB", "SLACK"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == EXPECTED_SEARCH_RESPONSE_KEYS
    assert body["status"] == "ok"
    assert body["query"] == "why did we change validation"
    assert body["totalResults"] == 0
    assert body["results"] == []


def test_search_missing_query_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/v1/rag/search",
            json={
                "userId": "employee_42",
                "groupIds": ["group_engineering"],
            },
        )
    assert response.status_code == 422


def test_search_unknown_field_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/v1/rag/search",
            json={
                "query": "test query",
                "userId": "employee_42",
                "extraField": "forbidden",
            },
        )
    assert response.status_code == 422


def test_ask_contract_response_matches_java_record() -> None:
    from app.api.internal_rag import get_grounded_rag_service
    from app.rag.service import GroundedRagService

    app = create_app()
    app.dependency_overrides[get_grounded_rag_service] = lambda: GroundedRagService(
        retriever=HybridRetriever(InMemoryKnowledgeRepository())
    )
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/rag/ask",
            json={
                "question": "why did we change validation",
                "userId": "employee_42",
                "groupIds": ["group_engineering", "group_backend"],
                "sourceTypes": ["GITHUB", "SLACK"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == EXPECTED_ASK_RESPONSE_KEYS
    assert body["question"] == "why did we change validation"
    assert body["status"] in {"ANSWERED", "INSUFFICIENT_EVIDENCE"}
    assert body["confidence"] in {"LOW", "MEDIUM"}
    assert isinstance(body["citations"], list)


def test_ask_missing_question_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/v1/rag/ask",
            json={
                "userId": "employee_42",
                "groupIds": ["group_engineering"],
            },
        )
    assert response.status_code == 422


def test_ask_unknown_field_is_rejected() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/v1/rag/ask",
            json={
                "question": "test question",
                "userId": "employee_42",
                "unexpectedField": "rejected",
            },
        )
    assert response.status_code == 422

