"""Tests for consolidated WorkMesh public API v1 endpoints in rag-python FastAPI service.

Validates:
- POST /api/v1/search (real hybrid results, searchTimeMs, status='SUCCESS', audit logging)
- POST /api/v1/ask (grounded answers, citations, audit logging, spoofed body ignored)
- GET /api/v1/sync/status & GET /api/v1/admin/sync/status (admin role enforcement, audit logging)
- GET /api/v1/admin/audit/events (admin role enforcement, filtering)
- Deterministic user context resolution via X-User-Id header
- Uniform error responses with populated traceId
- /ready verification of PostgreSQL
- Audit fail-open resilience
"""

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

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
)
from app.main import create_app


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
# Search Tests
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
    """POST /api/v1/search with blank query returns 400 Bad Request with uniform ErrorResponse and X-Request-Id."""
    response = client.post(
        "/api/v1/search",
        json={"query": "   "},
        headers={"X-Request-Id": "test-req-123"},
    )
    assert response.status_code == 400
    assert response.headers["X-Request-Id"] == "test-req-123"
    data = response.json()

    err = data["error"]
    assert err["code"] == "BAD_REQUEST"
    assert len(err["message"]) > 0
    assert err["request_id"] == "test-req-123"


# ---------------------------------------------------------------------------
# Ask Tests
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
    err = response.json()["error"]
    assert err["code"] == "BAD_REQUEST"
    assert err["request_id"]
    assert response.headers["X-Request-Id"] == err["request_id"]


# ---------------------------------------------------------------------------
# Sync Status Tests
# ---------------------------------------------------------------------------

def test_sync_status_forbidden_for_non_admin(client):
    """GET /api/v1/sync/status returns 403 Forbidden for standard user."""
    response = client.get("/api/v1/sync/status", headers={"X-User-Id": "employee_42"})
    assert response.status_code == 403
    err = response.json()["error"]
    assert err["code"] == "FORBIDDEN"
    assert "Access denied: ADMIN role required to view sync status" in err["message"]
    assert err["request_id"]


def test_admin_sync_status_forbidden_for_non_admin(client):
    """GET /api/v1/admin/sync/status returns 403 Forbidden for standard user."""
    response = client.get("/api/v1/admin/sync/status", headers={"X-User-Id": "employee_42"})
    assert response.status_code == 403
    err = response.json()["error"]
    assert err["code"] == "FORBIDDEN"
    assert err["request_id"]


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
# Audit Events Tests
# ---------------------------------------------------------------------------

def test_admin_audit_events_forbidden_for_non_admin(client):
    """GET /api/v1/admin/audit/events returns 403 Forbidden for non-admin user."""
    response = client.get("/api/v1/admin/audit/events", headers={"X-User-Id": "employee_42"})
    assert response.status_code == 403
    err = response.json()["error"]
    assert err["code"] == "FORBIDDEN"
    assert "Access denied: ADMIN role required to view audit events" in err["message"]
    assert err["request_id"]


def test_admin_audit_events_returns_events_for_admin(client, mock_repo):
    """GET /api/v1/admin/audit/events returns paginated events for ADMIN user."""
    mock_repo.record_audit_event("employee_42", "SEARCH", "hybrid", {"q": "auth"}, "127.0.0.1")
    mock_repo.record_audit_event("employee_admin", "SYNC_STATUS", "sync_state", {}, "127.0.0.1")

    response = client.get(
        "/api/v1/admin/audit/events",
        params={"userId": "employee_42", "action": "SEARCH", "limit": 20},
        headers={"X-User-Id": "employee_admin"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert data["hasMore"] is False
    assert len(data["items"]) == 1
    assert data["items"][0]["userId"] == "employee_42"
    assert data["items"][0]["action"] == "SEARCH"


def test_admin_audit_events_pagination(client, mock_repo):
    """GET /api/v1/admin/audit/events supports limit, offset, total, and hasMore."""
    for i in range(5):
        mock_repo.record_audit_event("employee_42", "SEARCH", "hybrid", {"seq": i}, "127.0.0.1")

    page1 = client.get(
        "/api/v1/admin/audit/events",
        params={"limit": 2, "offset": 0},
        headers={"X-User-Id": "employee_admin"},
    ).json()
    assert page1["total"] == 5
    assert page1["limit"] == 2
    assert page1["offset"] == 0
    assert page1["hasMore"] is True
    assert len(page1["items"]) == 2

    page3 = client.get(
        "/api/v1/admin/audit/events",
        params={"limit": 2, "offset": 4},
        headers={"X-User-Id": "employee_admin"},
    ).json()
    assert page3["total"] == 5
    assert page3["hasMore"] is False
    assert len(page3["items"]) == 1


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
# Readiness & Health Tests
# ---------------------------------------------------------------------------

def test_health_liveness(client):
    """/health reports ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


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
    err = response.json()["error"]
    assert err["code"] == "SERVICE_UNAVAILABLE"
    assert "database service is unavailable" in err["message"]
    assert err["request_id"]


# ---------------------------------------------------------------------------
# Error & Resilience Tests
# ---------------------------------------------------------------------------

def test_ask_when_rag_service_unavailable_returns_503(mock_repo, mock_retriever):
    """Database failure during /ask returns 503."""
    class FailingRagService:
        def ask(self, request):
            raise DatabaseUnavailableError("PostgreSQL connection refused")

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: mock_repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: mock_retriever
    app.dependency_overrides[get_grounded_rag_service] = lambda: FailingRagService()
    test_client = TestClient(app)

    response = test_client.post(
        "/api/v1/ask",
        json={"question": "why did validation change"},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 503
    err = response.json()["error"]
    assert err["code"] == "SERVICE_UNAVAILABLE"
    assert "database service is unavailable" in err["message"]
    assert err["request_id"]


def test_ask_when_internal_error_returns_500(mock_repo, mock_retriever):
    """Unhandled exception during /ask returns 500."""
    class CrashingRagService:
        def ask(self, request):
            raise RuntimeError("Unexpected pipeline crash")

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: mock_repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: mock_retriever
    app.dependency_overrides[get_grounded_rag_service] = lambda: CrashingRagService()
    test_client = TestClient(app, raise_server_exceptions=False)

    response = test_client.post(
        "/api/v1/ask",
        json={"question": "why did validation change"},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 500
    err = response.json()["error"]
    assert err["code"] == "INTERNAL_ERROR"
    assert err["request_id"]


def test_ask_audit_remains_recorded_when_rag_client_throws_exception(mock_repo, mock_retriever):
    """Audit event remains logged even when RAG processing throws an exception."""
    class FailingRagService:
        def ask(self, request):
            raise RuntimeError("RAG processing failed")

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: mock_repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: mock_retriever
    app.dependency_overrides[get_grounded_rag_service] = lambda: FailingRagService()
    test_client = TestClient(app, raise_server_exceptions=False)

    response = test_client.post(
        "/api/v1/ask",
        json={"question": "audit persistence check"},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 500

    # Verify audit event was still written to repo
    events = mock_repo.get_audit_events(user_id="employee_42", action="ASK")
    assert len(events) == 1
    assert events[0]["details"]["question"] == "audit persistence check"


def test_ask_handles_insufficient_evidence_with_empty_citations(client, mock_rag_service):
    """Returns INSUFFICIENT_EVIDENCE with empty citations when no evidence matches."""
    mock_rag_service.response = RagAskResponse(
        question="What is the quantum encryption secret?",
        answer="I cannot answer this question based on the authorized documents available to you.",
        citations=[],
        confidence="LOW",
        status="INSUFFICIENT_EVIDENCE",
    )

    response = client.post(
        "/api/v1/ask",
        json={"question": "What is the quantum encryption secret?"},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "INSUFFICIENT_EVIDENCE"
    assert data["confidence"] == "LOW"
    assert data["citations"] == []


def test_search_when_retriever_fails_returns_503(mock_repo):
    """Search returns 503 with ApiError shape when database query fails."""
    class FailingRetriever:
        def search(self, *args, **kwargs):
            raise DatabaseUnavailableError("Database query failed")

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: mock_repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: FailingRetriever()
    test_client = TestClient(app)

    response = test_client.post(
        "/api/v1/search",
        json={"query": "payment"},
        headers={"X-User-Id": "employee_42"},
    )
    assert response.status_code == 503
    err = response.json()["error"]
    assert err["code"] == "SERVICE_UNAVAILABLE"
    assert err["request_id"]


def test_structured_json_logging_includes_request_id():
    """Structured JSON formatter emits parseable JSON with top-level request_id."""
    import io
    import json
    import logging

    from app.main import JsonLogFormatter

    app = create_app()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonLogFormatter())
    http_logger = logging.getLogger("workmesh.http")
    http_logger.addHandler(handler)
    try:
        client = TestClient(app)
        resp = client.get("/health", headers={"X-Request-Id": "req-json-log-99"})
        assert resp.status_code == 200
        assert resp.headers["X-Request-Id"] == "req-json-log-99"

        lines = [line for line in stream.getvalue().splitlines() if line.strip()]
        assert lines
        parsed = json.loads(lines[-1])
        assert parsed["level"] == "INFO"
        assert parsed["request_id"] == "req-json-log-99"
    finally:
        http_logger.removeHandler(handler)
