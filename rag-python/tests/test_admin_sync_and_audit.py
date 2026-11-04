"""Unit and integration tests for internal sync status and audit persistence endpoints.

Tests /internal/v1/sync/status and /internal/v1/audit/events.
"""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.api.internal_rag import get_repository
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


# ---------------------------------------------------------------------------
# 1. Sync Status Tests
# ---------------------------------------------------------------------------

def test_sync_status_defaults_to_idle(client: TestClient):
    """When no connectors have run, all sources and overall status are IDLE."""
    resp = client.get("/internal/v1/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overallStatus"] == "IDLE"
    assert len(data["sources"]) == 3
    source_types = [s["sourceType"] for s in data["sources"]]
    assert set(source_types) == {"GITHUB", "SLACK", "EMAIL"}
    for s in data["sources"]:
        assert s["status"] == "IDLE"
        assert s["recordsSyncedLastRun"] == 0


def test_sync_status_reports_connector_states_and_running(client: TestClient, repo: InMemoryKnowledgeRepository):
    """When a connector is RUNNING, overallStatus derives as RUNNING."""
    now = datetime.now(timezone.utc)
    repo.update_sync_state(
        SyncStateRecord(
            source_type="GITHUB",
            cursor_value="cursor_gh_123",
            status="SUCCESS",
            last_sync_started_at=now,
            last_sync_completed_at=now,
            records_synced_last_run=42,
        )
    )
    repo.update_sync_state(
        SyncStateRecord(
            source_type="SLACK",
            cursor_value="cursor_sl_456",
            status="RUNNING",
            last_sync_started_at=now,
            records_synced_last_run=0,
        )
    )

    resp = client.get("/internal/v1/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overallStatus"] == "RUNNING"
    gh = next(s for s in data["sources"] if s["sourceType"] == "GITHUB")
    assert gh["status"] == "SUCCESS"
    assert gh["cursor"] == "cursor_gh_123"
    assert gh["recordsSyncedLastRun"] == 42
    sl = next(s for s in data["sources"] if s["sourceType"] == "SLACK")
    assert sl["status"] == "RUNNING"


def test_sync_status_reports_failed_overall(client: TestClient, repo: InMemoryKnowledgeRepository):
    """When any connector has status FAILED, overallStatus derives as FAILED."""
    repo.update_sync_state(
        SyncStateRecord(
            source_type="EMAIL",
            cursor_value="cursor_em_789",
            status="FAILED",
            error_message="IMAP connection timed out",
        )
    )

    resp = client.get("/internal/v1/sync/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overallStatus"] == "FAILED"
    em = next(s for s in data["sources"] if s["sourceType"] == "EMAIL")
    assert em["status"] == "FAILED"
    assert em["errorMessage"] == "IMAP connection timed out"


# ---------------------------------------------------------------------------
# 2. Audit Events Persistence Tests
# ---------------------------------------------------------------------------

def test_record_and_get_audit_events(client: TestClient):
    """Posting audit events persists them and retrieving returns them ordered by timestamp."""
    event1 = {
        "userId": "employee_42",
        "action": "SEARCH",
        "resource": "hybrid_search",
        "details": {"query": "deployment checklist", "top_k": 5},
        "ipAddress": "127.0.0.1",
    }
    resp1 = client.post("/internal/v1/audit/events", json=event1)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "ok"

    event2 = {
        "userId": "employee_admin",
        "action": "SYNC_STATUS",
        "resource": "sync_state",
        "details": {},
        "ipAddress": "127.0.0.1",
    }
    resp2 = client.post("/internal/v1/audit/events", json=event2)
    assert resp2.status_code == 200

    # Retrieve all
    get_resp = client.get("/internal/v1/audit/events")
    assert get_resp.status_code == 200
    events = get_resp.json()
    assert len(events) == 2
    # Check descending order: most recent event (event2) first
    assert events[0]["action"] == "SYNC_STATUS"
    assert events[0]["userId"] == "employee_admin"
    assert events[1]["action"] == "SEARCH"
    assert events[1]["userId"] == "employee_42"
    assert events[1]["details"]["top_k"] == 5


def test_get_audit_events_filtering_and_limits(client: TestClient):
    """Filtering by userId, action, and limit works as expected."""
    for i in range(10):
        client.post(
            "/internal/v1/audit/events",
            json={
                "userId": f"employee_{i % 2}",
                "action": "SEARCH" if i % 2 == 0 else "ASK",
                "resource": f"query_{i}",
                "details": {"index": i},
            },
        )

    # Filter by user
    resp = client.get("/internal/v1/audit/events?userId=employee_0")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 5
    assert all(e["userId"] == "employee_0" for e in events)

    # Filter by action
    resp_act = client.get("/internal/v1/audit/events?action=ASK")
    assert resp_act.status_code == 200
    events_act = resp_act.json()
    assert len(events_act) == 5
    assert all(e["action"] == "ASK" for e in events_act)

    # Limit
    resp_lim = client.get("/internal/v1/audit/events?limit=3")
    assert resp_lim.status_code == 200
    events_lim = resp_lim.json()
    assert len(events_lim) == 3


# ---------------------------------------------------------------------------
# 3. Live PostgreSQL Audit Persistence Test (if container available)
# ---------------------------------------------------------------------------

def _detect_pg_url():
    import psycopg
    from app.common.config import get_settings
    settings = get_settings()
    custom_test_url = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}@"
        f"{settings.postgres_host}:{settings.postgres_port}/test_knowledge"
    )
    candidates = [
        custom_test_url,
        "postgresql://knowledge:local_dev_only_change_me@localhost:5432/test_knowledge",
        "postgresql://knowledge:local_dev_only_change_me@127.0.0.1:5432/test_knowledge",
    ]
    for u in candidates:
        try:
            with psycopg.connect(u, connect_timeout=1) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    return u
        except Exception:
            continue
    return None


def test_live_postgres_audit_events_persistence():
    """Verify durable audit event insertion and descending retrieval in PostgreSQL."""
    pg_url = _detect_pg_url()
    if not pg_url:
        pytest.skip("Live PostgreSQL container not reachable")

    from app.indexing.repository import PostgresKnowledgeRepository
    repo = PostgresKnowledgeRepository(connection_url=pg_url)

    uid = "test_user_live_audit_99"
    repo.record_audit_event(
        user_id=uid,
        action="TEST_ACTION_A",
        resource="res_a",
        details={"key": "val1"},
        ip_address="127.0.0.1",
    )
    repo.record_audit_event(
        user_id=uid,
        action="TEST_ACTION_B",
        resource="res_b",
        details={"key": "val2"},
        ip_address="127.0.0.1",
    )

    events = repo.get_audit_events(user_id=uid, limit=10)
    assert len(events) >= 2
    # Check descending order: most recent action B should be first
    assert events[0]["action"] == "TEST_ACTION_B"
    assert events[0]["userId"] == uid
    assert events[0]["details"]["key"] == "val2"
    assert events[1]["action"] == "TEST_ACTION_A"
    assert events[1]["details"]["key"] == "val1"

