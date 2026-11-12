"""Tests for the liveness and readiness endpoints."""

from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.indexing.repository import DatabaseUnavailableError, InMemoryKnowledgeRepository
from app.main import create_app


def test_health_reports_ok_even_when_database_down() -> None:
    """/health must stay independent of PostgreSQL availability."""
    class FailingRepo(InMemoryKnowledgeRepository):
        def check_health(self) -> bool:
            raise DatabaseUnavailableError("connection failed")

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: FailingRepo()
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "rag-python"}


def test_ready_reports_ok() -> None:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: InMemoryKnowledgeRepository()
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "rag-python", "database": "ok"}


def test_ready_reports_503_when_database_is_unavailable() -> None:
    class FailingRepo(InMemoryKnowledgeRepository):
        def check_health(self) -> bool:
            raise DatabaseUnavailableError("connection failed")

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: FailingRepo()
    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
