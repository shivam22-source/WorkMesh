"""Tests for Prometheus operational metrics endpoint."""

from fastapi.testclient import TestClient

from app.api.metrics import reset_metrics_for_testing
from app.dependencies import get_repository
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app


def test_metrics_endpoint_exports_prometheus_format():
    reset_metrics_for_testing()
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: InMemoryKnowledgeRepository()
    client = TestClient(app)

    # Generate some HTTP traffic
    client.get("/health")
    client.get("/ready")
    client.post("/api/v1/search", json={"query": "test query"}, headers={"X-User-Id": "employee_42"})

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text

    assert "workmesh_http_requests_total" in body
    assert 'path="/health"' in body
    assert 'path="/ready"' in body
    assert 'path="/api/v1/search"' in body
    assert "workmesh_search_queries_total 1" in body
    assert "workmesh_http_request_duration_seconds" in body
