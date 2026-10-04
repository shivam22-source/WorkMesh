"""Contract tests for POST /internal/v1/rag/health.

These are the Python-side guard against drift. They assert the exact wire
shape that backend-java's `RagHealthResponse` record expects, so a rename on one
side fails a test on the other side instead of failing at runtime.

The literal `EXPECTED_KEYS` assertion is intentional: it will fail if someone
adds or removes a field without updating the Java record and this file together.
"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app

EXPECTED_RESPONSE_KEYS = {"status", "service", "contractVersion", "message"}


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

    assert set(body.keys()) == EXPECTED_RESPONSE_KEYS
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