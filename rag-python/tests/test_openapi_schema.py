"""Tests for OpenAPI specification and Swagger UI availability."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_openapi_schema_generation():
    app = create_app()
    client = TestClient(app)

    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    assert schema["info"]["title"] == "WorkMesh Platform API"
    assert schema["info"]["version"] == "1.0.0"

    # Verify tags metadata exists
    tag_names = [t["name"] for t in schema.get("tags", [])]
    assert "public_v1" in tag_names
    assert "health" in tag_names
    assert "metrics" in tag_names

    # Verify primary endpoints exist in paths
    paths = schema["paths"]
    assert "/api/v1/search" in paths
    assert "/api/v1/ask" in paths
    assert "/api/v1/sync/status" in paths
    assert "/health" in paths
    assert "/ready" in paths
    assert "/metrics" in paths

    # Verify polished API schemas exist
    schemas = schema.get("components", {}).get("schemas", {})
    assert "ErrorResponse" in schemas
    assert "PaginatedAuditEventsResponse" in schemas
    assert "LivenessResponse" in schemas
    assert "ReadinessResponse" in schemas


def test_swagger_and_redoc_endpoints():
    app = create_app()
    client = TestClient(app)

    res_docs = client.get("/docs")
    assert res_docs.status_code == 200

    res_redoc = client.get("/redoc")
    assert res_redoc.status_code == 200
