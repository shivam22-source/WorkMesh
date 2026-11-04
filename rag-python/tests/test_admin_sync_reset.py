"""Unit and security tests for connector sync lease reset admin endpoint."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_repository
from app.indexing.models import SyncStateRecord
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app


@pytest.fixture
def repo() -> InMemoryKnowledgeRepository:
    return InMemoryKnowledgeRepository()


@pytest.fixture
def client(repo: InMemoryKnowledgeRepository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(app)


def test_admin_sync_reset_requires_admin_role(client: TestClient):
    """Non-admin user cannot reset sync state."""
    resp = client.post(
        "/api/v1/admin/sync/reset",
        json={"sourceType": "GITHUB"},
        headers={"X-User-Id": "regular_eng"},
    )
    assert resp.status_code == 403
    assert "ADMIN role required" in resp.json()["message"]


def test_admin_sync_reset_single_source(client: TestClient, repo: InMemoryKnowledgeRepository):
    """Admin can reset a stuck or failed connector to IDLE."""
    now = datetime.now(timezone.utc)
    repo.update_sync_state(
        SyncStateRecord(
            source_type="GITHUB",
            cursor_value="cursor_gh_999",
            status="FAILED",
            last_sync_started_at=now,
            error_message="Connection timed out after 3 retries",
        )
    )

    resp = client.post(
        "/api/v1/admin/sync/reset",
        json={"sourceType": "GITHUB"},
        headers={"X-User-Id": "employee_admin"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sourceType"] == "GITHUB"
    assert data["status"] == "RESET"
    assert data["resetSources"] == ["GITHUB"]

    # Verify repository state
    state = repo.get_sync_state("GITHUB")
    assert state is not None
    assert state.status == "IDLE"
    assert state.error_message is None
    # Cursor preserved for resuming
    assert state.cursor_value == "cursor_gh_999"

    # Verify audit event recorded
    events = repo.get_audit_events(action="SYNC_RESET")
    assert len(events) == 1
    assert events[0]["userId"] == "employee_admin"
    assert events[0]["resource"] == "sync_state:GITHUB"


def test_admin_sync_reset_all_sources(client: TestClient, repo: InMemoryKnowledgeRepository):
    """Admin can reset all connectors at once using 'ALL'."""
    repo.update_sync_state(
        SyncStateRecord(
            source_type="SLACK",
            status="RUNNING",
            error_message="Stale lease held",
        )
    )
    repo.update_sync_state(
        SyncStateRecord(
            source_type="EMAIL",
            status="FAILED",
            error_message="IMAP auth failure",
        )
    )

    resp = client.post(
        "/api/v1/admin/sync/reset",
        json={"sourceType": "ALL"},
        headers={"X-User-Id": "employee_admin"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sourceType"] == "ALL"
    assert set(data["resetSources"]) == {"GITHUB", "SLACK", "EMAIL"}

    assert repo.get_sync_state("SLACK").status == "IDLE"
    assert repo.get_sync_state("EMAIL").status == "IDLE"


def test_admin_sync_reset_invalid_source_rejected(client: TestClient):
    """Invalid source types return 400 Bad Request."""
    resp = client.post(
        "/api/v1/admin/sync/reset",
        json={"sourceType": "UNKNOWN_SOURCE"},
        headers={"X-User-Id": "employee_admin"},
    )
    assert resp.status_code == 400
    assert "Invalid sourceType" in resp.json()["message"]
