"""Tests for concurrency limits, backpressure 503 with Retry-After, and per-stage timings."""

import pytest
from fastapi.testclient import TestClient

from app.api.concurrency import ConcurrencyLimiter, search_concurrency_limiter
from app.api.metrics import record_request_metric, reset_metrics_for_testing
from app.contracts.rag_search import RagSearchResultItem
from app.dependencies import get_hybrid_retriever, get_repository
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app


class MockRetrieverWithTimings:
    def __init__(self):
        self.last_stage_timings = {
            "lexicalMs": 4.5,
            "vectorMs": 8.2,
            "fuseMs": 1.1,
            "graphMs": 0.0,
        }

    def search(self, *args, **kwargs):
        return [
            RagSearchResultItem(
                chunk_id="chunk:test:1",
                document_id="doc:test:1",
                source_type="GITHUB",
                title="PR Title",
                snippet="Snippet content",
                source_url="https://github.com/company/repo/pull/1",
                score=0.95,
            )
        ]


@pytest.fixture
def test_client():
    app = create_app()
    mock_repo = InMemoryKnowledgeRepository()
    mock_retriever = MockRetrieverWithTimings()
    app.dependency_overrides[get_repository] = lambda: mock_repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: mock_retriever
    return TestClient(app)


def test_search_returns_per_stage_timings(test_client):
    """POST /api/v1/search includes per-stage breakdown timings."""
    resp = test_client.post(
        "/api/v1/search",
        json={"query": "payment card verification"},
        headers={"X-User-Id": "employee_42"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "timings" in data
    assert data["timings"] is not None
    assert data["timings"]["lexicalMs"] == 4.5
    assert data["timings"]["vectorMs"] == 8.2
    assert data["timings"]["fuseMs"] == 1.1
    assert data["timings"]["graphMs"] == 0.0


def test_concurrency_limiter_rejects_with_503_and_retry_after(test_client):
    """When concurrency is saturated, API returns 503 with Retry-After header."""
    search_concurrency_limiter.reset_for_testing()
    # Artificially saturate the limiter
    search_concurrency_limiter._active_count = search_concurrency_limiter.max_concurrent

    try:
        resp = test_client.post(
            "/api/v1/search",
            json={"query": "payment"},
            headers={"X-User-Id": "employee_42"},
        )
        assert resp.status_code == 503
        assert "Retry-After" in resp.headers
        assert resp.headers["Retry-After"] == "1"
        data = resp.json()
        assert data["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "concurrency limit" in data["error"]["message"].lower()
        assert data["error"]["request_id"]

        # Same for /ask
        resp_ask = test_client.post(
            "/api/v1/ask",
            json={"question": "why did validation change?"},
            headers={"X-User-Id": "employee_42"},
        )
        assert resp_ask.status_code == 503
        assert "Retry-After" in resp_ask.headers
    finally:
        search_concurrency_limiter.reset_for_testing()


def test_metrics_exposes_p95_latency(test_client):
    """GET /metrics exposes p95 quantile and dedicated search p95 gauge."""
    reset_metrics_for_testing()
    for duration in [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]:
        record_request_metric("POST", "/api/v1/search", 200, duration)

    resp = test_client.get("/metrics")
    assert resp.status_code == 200
    content = resp.text

    assert 'quantile="0.95"' in content
    assert "workmesh_search_latency_p95_seconds" in content


def test_concurrency_limiter_allows_exact_n_concurrent_and_sheds_excess():
    """Limiter must allow exactly N concurrent requests and shed only the excess."""
    limiter = ConcurrencyLimiter(max_concurrent=3)
    assert limiter.acquire() is True
    assert limiter.acquire() is True
    assert limiter.acquire() is True
    # 4th request must be shed (False)
    assert limiter.acquire() is False
    assert limiter.active_count == 3

    # Release one
    limiter.release()
    assert limiter.active_count == 2

    # Now one can acquire again
    assert limiter.acquire() is True
    # And 4th is shed again
    assert limiter.acquire() is False
