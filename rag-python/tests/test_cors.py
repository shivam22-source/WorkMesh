"""Tests for CORS middleware behavior."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_cors_preflight_and_headers():
    app = create_app()
    client = TestClient(app)

    # Test preflight OPTIONS request
    response = client.options(
        "/api/v1/search",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-User-Id,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in response.headers["access-control-allow-methods"]

    # Test GET request with Origin
    res_health = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert res_health.status_code == 200
    assert res_health.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "X-Trace-Id" in res_health.headers.get("access-control-expose-headers", "")
