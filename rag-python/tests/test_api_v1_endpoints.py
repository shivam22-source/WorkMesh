"""Tests porting all backend-java functionality into rag-python FastAPI service.

Validates:
- POST /api/v1/search (real hybrid results, searchTimeMs, status='SUCCESS', audit logging)
- POST /api/v1/ask (grounded answers, citations, audit logging, spoofed body ignored)
- GET /api/v1/sync/status & GET /api/v1/admin/sync/status (admin role enforcement, audit logging)
- GET /api/v1/admin/audit/events (admin role enforcement, filtering)
- Deterministic user context resolution via X-User-Id header
- Uniform ApiError responses with populated traceId
- /ready verification of PostgreSQL
- Audit fail-open resilience
"""

import time
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from app.auth.user_context import UserContext, get_current_user
from app.contracts.rag_ask import CitationItem, RagAskRequest, RagAskResponse
from app.contracts.rag_search import RagSearchResultItem
from app.dependencies import (
    get_grounded_rag_service,
    get_hybrid_retriever,
    get_repository,
)
from app.indexing.repository import (
    DatabaseUnavailableError,
    InMemoryKnowledgeRepository,
    SyncStateRecord,
)
from app.main import create_app
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever


class MockRetriever:
    def __init__(self, items: Optional[List[RagSearchResultItem]] = None):
        self.items = items or [
            RagSearchResultItem(
                chunk_id="chunk_1",
                document_id="doc_1",
                source_type="GITHUB",
                title="Validation Fix",
                snippet="Fixed null checks",
                source_url="https://github.com/company/repo/pull/1",
                author="Alex Engineer",
                score=0.92,
            )
        ]
        self.last_search_call: Optional[Dict[str, Any]] = None

    def search(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        self.last_search_call = {
            "query": query,
            "limit": limit,
            "source_types": source_types,
            "user_id": user_id,
            "group_ids": group_ids,
        }
        return self.items


class MockRagService:
    def __init__(self, response: Optional[RagAskResponse] = None):
        self.response = response or RagAskResponse(
            question="why did validation change",
            answer="According to the available evidence: validation updated [1]",
            citations=[
                CitationItem(
                    source_type="GITHUB",
                    title="Fix validation flow",
                    url="https://github.com/company/repo/pull/123",
                    snippet="Updated validation logic in PR #123",
                )
            ],
            confidence="MEDIUM",
            status="ANSWERED",
        )
        self.last_ask_request: Optional[RagAskRequest] = None

    def ask(self, request: RagAskRequest) -> RagAskResponse:
        self.last_ask_request = request
        return self.response


@pytest.fixture
def mock_repo():
    repo = InMemoryKnowledgeRepository()
    return repo


@pytest.fixture
def mock_retriever():
    return MockRetriever()


@pytest.fixture
def mock_rag_service():
    return MockRagService()


@pytest.fixture
def client(mock_repo, mock_retriever, mock_rag_service):
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: mock_repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: mock_retriever
    app.dependency_overrides[get_grounded_rag_service] = lambda: mock_rag_service
    return TestClient(app)


# ---------------------------------------------------------------------------
# Search Tests (SearchControllerTest.java port)
# ---------------------------------------------------------------------------

def test_search_returns_results_with_success_status_and_time(client, mock_repo, mock_retriever):
    """POST /api/v1/search returns 200, status='SUCCESS' (not 'STUB'), searchTimeMs, and records audit."""
    response = client.post(
        "/api/v1/search",
        json={"query": "validation", "limit": 10},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["query"] == "validation"
    assert data["totalResults"] == 1
    assert data["status"] == "SUCCESS"  # Verified STUB is eliminated
    assert "searchTimeMs" in data
    assert isinstance(data["searchTimeMs"], int)
    assert len(data["results"]) == 1
    assert data["results"][0]["chunkId"] == "chunk_1"
    assert data["results"][0]["sourceType"] == "GITHUB"

    # Verify audit event was logged
    audit_events = mock_repo.get_audit_events(user_id="employee_42", action="SEARCH")
    assert len(audit_events) == 1
    assert audit_events[0]["action"] == "SEARCH"
    assert audit_events[0]["details"]["query"] == "validation"


def test_search_blank_query_returns_bad_request_with_apierror_shape(client):
    """POST /api/v1/search with blank query returns 400 Bad Request with ApiError shape and populated traceId."""
    response = client.post(
        "/api/v1/search",
        json={"query": "   "},
        headers={"X-Trace-Id": "test-trace-123"},
    )
    assert response.status_code == 400
    data = response.json()

    assert data["status"] == 400
    assert data["error"] == "Bad Request"
    assert "message" in data and len(data["message"]) > 0
    assert data["path"] == "/api/v1/search"
    assert data["traceId"] == "test-trace-123"
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Ask Tests (SearchControllerTest.java port)
# ---------------------------------------------------------------------------

def test_ask_returns_grounded_answer_and_citations(client, mock_repo):
    """POST /api/v1/ask returns 200, grounded answer, citations, confidence, status, and records audit."""
    response = client.post(
        "/api/v1/ask",
        json={"question": "why did validation change"},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["question"] == "why did validation change"
    assert "validation updated [1]" in data["answer"]
    assert data["status"] == "ANSWERED"
    assert data["confidence"] == "MEDIUM"
    assert len(data["citations"]) == 1
    assert data["citations"][0]["sourceType"] == "GITHUB"
    assert data["citations"][0]["title"] == "Fix validation flow"

    # Verify audit event was recorded
    audit_events = mock_repo.get_audit_events(user_id="employee_42", action="ASK")
    assert len(audit_events) == 1
    assert audit_events[0]["details"]["question"] == "why did validation change"


def test_ask_ignores_spoofed_identity_in_body(client, mock_rag_service):
    """POST /api/v1/ask ignores spoofed identity in JSON body and preserves server-side UserContext."""
    response = client.post(
        "/api/v1/ask",
        json={
            "question": "why did validation change",
            "userId": "attacker_id",
            "groupIds": ["admin_group"],
        },
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 200

    captured = mock_rag_service.last_ask_request
    assert captured is not None
    assert captured.user_id == "employee_42"
    assert set(captured.group_ids) == {"group_engineering", "group_backend"}


def test_ask_blank_question_returns_bad_request(client):
    """POST /api/v1/ask with blank question returns 400 Bad Request."""
    response = client.post(
        "/api/v1/ask",
        json={"question": ""},
    )
    assert response.status_code == 400
    data = response.json()
    assert data["status"] == 400
    assert data["path"] == "/api/v1/ask"
    assert data["traceId"] is not None


# ---------------------------------------------------------------------------
# Sync Status Tests (SyncControllerTest.java port)
# ---------------------------------------------------------------------------

def test_sync_status_forbidden_for_non_admin(client):
    """GET /api/v1/sync/status returns 403 Forbidden for standard user."""
    response = client.get("/api/v1/sync/status", headers={"X-User-Id": "employee_42"})
    assert response.status_code == 403
    data = response.json()
    assert data["status"] == 403
    assert data["error"] == "Forbidden"
    assert "Access denied: ADMIN role required to view sync status" in data["message"]
    assert data["traceId"] is not None


def test_admin_sync_status_forbidden_for_non_admin(client):
    """GET /api/v1/admin/sync/status returns 403 Forbidden for standard user."""
    response = client.get("/api/v1/admin/sync/status", headers={"X-User-Id": "employee_42"})
    assert response.status_code == 403
    data = response.json()
    assert data["status"] == 403
    assert data["error"] == "Forbidden"


def test_sync_status_reports_sources_for_admin(client, mock_repo):
    """GET /api/v1/sync/status returns 200 and records audit for ADMIN user."""
    response = client.get("/api/v1/sync/status", headers={"X-User-Id": "employee_admin"})
    assert response.status_code == 200
    data = response.json()

    assert data["overallStatus"] == "IDLE"
    assert isinstance(data["sources"], list)
    source_types = [s["sourceType"] for s in data["sources"]]
    assert "GITHUB" in source_types
    assert "SLACK" in source_types
    assert "EMAIL" in source_types

    # Verify audit event was logged
    audit_events = mock_repo.get_audit_events(user_id="employee_admin", action="SYNC_STATUS")
    assert len(audit_events) == 1


def test_admin_sync_status_reports_sources_for_admin(client):
    """GET /api/v1/admin/sync/status returns 200 for ADMIN user."""
    response = client.get("/api/v1/admin/sync/status", headers={"X-User-Id": "employee_admin"})
    assert response.status_code == 200
    assert response.json()["overallStatus"] == "IDLE"


# ---------------------------------------------------------------------------
# Audit Events Tests (AuditControllerTest.java port)
# ---------------------------------------------------------------------------

def test_admin_audit_events_forbidden_for_non_admin(client):
    """GET /api/v1/admin/audit/events returns 403 Forbidden for non-admin user."""
    response = client.get("/api/v1/admin/audit/events", headers={"X-User-Id": "employee_42"})
    assert response.status_code == 403
    data = response.json()
    assert data["status"] == 403
    assert data["error"] == "Forbidden"
    assert "Access denied: ADMIN role required to view audit events" in data["message"]


def test_admin_audit_events_returns_events_for_admin(client, mock_repo):
    """GET /api/v1/admin/audit/events returns 200 OK and events for ADMIN user."""
    mock_repo.record_audit_event("employee_42", "SEARCH", "hybrid", {"q": "auth"}, "127.0.0.1")
    mock_repo.record_audit_event("employee_admin", "SYNC_STATUS", "sync_state", {}, "127.0.0.1")

    response = client.get(
        "/api/v1/admin/audit/events",
        params={"userId": "employee_42", "action": "SEARCH", "limit": 20},
        headers={"X-User-Id": "employee_admin"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["userId"] == "employee_42"
    assert data[0]["action"] == "SEARCH"


def test_audit_safe_fail_open_resilience(client, mock_repo, monkeypatch):
    """Search/Ask succeed even if audit event recording throws."""
    def failing_record_audit(*args, **kwargs):
        raise RuntimeError("Audit datastore down")

    monkeypatch.setattr(mock_repo, "record_audit_event", failing_record_audit)

    response = client.post(
        "/api/v1/search",
        json={"query": "test query"},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Readiness & Health Tests (HealthEndpointTest.java port + DB check)
# ---------------------------------------------------------------------------

def test_health_liveness_and_actuator_compatibility(client):
    """/health and /actuator/health report UP."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_actuator = client.get("/actuator/health")
    assert res_actuator.status_code == 200
    assert res_actuator.json()["status"] == "UP"


def test_ready_reports_ok_when_database_is_healthy(client):
    """/ready checks database and returns 200 when healthy."""
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_503_when_database_is_unavailable(mock_repo):
    """/ready checks database and returns 503 when Postgres is down."""
    class FailingRepo(InMemoryKnowledgeRepository):
        def check_health(self) -> bool:
            raise DatabaseUnavailableError("PostgreSQL connection refused")

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: FailingRepo()
    test_client = TestClient(app)

    response = test_client.get("/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == 503
    assert data["error"] == "Service Unavailable"
    assert "database service is unavailable" in data["message"]
    assert data["traceId"] is not None
