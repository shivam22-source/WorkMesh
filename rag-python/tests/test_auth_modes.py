"""Tests for authentication modes: production JWT verification vs dev header simulation."""

import time
import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_utils import create_jwt_token
from app.common.config import Settings, get_settings
from app.dependencies import get_hybrid_retriever, get_repository
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.retrieval.hybrid import HybridRetriever


@pytest.fixture
def repo() -> InMemoryKnowledgeRepository:
    return InMemoryKnowledgeRepository()


@pytest.fixture
def retriever(repo: InMemoryKnowledgeRepository) -> HybridRetriever:
    return HybridRetriever(repository=repo)


def test_prod_mode_rejects_forged_role_header(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, any simulation headers (X-User-*) are strictly rejected with 401."""
    prod_settings = Settings(auth_mode="prod")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    # Attempt to forge ADMIN role via header
    resp = client.get(
        "/api/v1/admin/sync/status",
        headers={"X-User-Role": "ADMIN", "X-User-Id": "forged_admin"},
    )
    assert resp.status_code == 401
    assert "forbidden in production mode" in resp.json()["message"]


def test_prod_mode_rejects_missing_jwt(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, requests lacking an Authorization Bearer token fail closed with 401."""
    prod_settings = Settings(auth_mode="prod")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    resp = client.post(
        "/api/v1/search",
        json={"query": "architecture overview"},
    )
    assert resp.status_code == 401
    assert "Missing Authorization header" in resp.json()["message"]


def test_prod_mode_accepts_valid_jwt(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, a properly signed and non-expired JWT is accepted."""
    prod_settings = Settings(auth_mode="prod")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    token = create_jwt_token(
        user_id="alice_eng",
        role="ENGINEER",
        groups=["group_engineering"],
        secret=prod_settings.jwt_secret,
        expires_in_seconds=3600,
    )

    resp = client.post(
        "/api/v1/search",
        json={"query": "test query"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"


def test_prod_mode_rejects_expired_jwt(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, an expired JWT is rejected with 401."""
    prod_settings = Settings(auth_mode="prod")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    # Token expired 10 seconds ago
    token = create_jwt_token(
        user_id="alice_eng",
        role="ENGINEER",
        secret=prod_settings.jwt_secret,
        expires_in_seconds=-10,
    )

    resp = client.post(
        "/api/v1/search",
        json={"query": "test query"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
    assert "Token has expired" in resp.json()["message"]


def test_prod_mode_rejects_tampered_jwt(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, a JWT signed with a different key or tampered signature is rejected with 401."""
    prod_settings = Settings(auth_mode="prod")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    # Token signed with untrusted secret key
    bad_token = create_jwt_token(
        user_id="attacker",
        role="ADMIN",
        secret="attacker_untrusted_secret_key_123456",
        expires_in_seconds=3600,
    )

    resp = client.post(
        "/api/v1/search",
        json={"query": "test query"},
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert resp.status_code == 401
    assert "Invalid token signature" in resp.json()["message"]


def test_prod_mode_require_admin_role_enforcement(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, valid JWT without ADMIN role receives 403 Forbidden on admin endpoints."""
    prod_settings = Settings(auth_mode="prod")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    # 1. Non-admin engineer token calling admin endpoint -> 403
    eng_token = create_jwt_token(
        user_id="bob_eng",
        role="ENGINEER",
        secret=prod_settings.jwt_secret,
    )
    resp_forbidden = client.get(
        "/api/v1/admin/sync/status",
        headers={"Authorization": f"Bearer {eng_token}"},
    )
    assert resp_forbidden.status_code == 403
    assert "ADMIN role required" in resp_forbidden.json()["message"]

    # 2. Admin token calling admin endpoint -> 200
    admin_token = create_jwt_token(
        user_id="sarah_admin",
        role="ADMIN",
        secret=prod_settings.jwt_secret,
    )
    resp_ok = client.get(
        "/api/v1/admin/sync/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["overallStatus"] == "IDLE"


def test_dev_mode_still_works(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In dev mode, header-based simulation functions and logs startup warning."""
    dev_settings = Settings(auth_mode="dev")
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: dev_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    # In dev mode, X-User-Role: ADMIN is respected
    resp_admin = client.get(
        "/api/v1/admin/sync/status",
        headers={"X-User-Id": "employee_admin", "X-User-Role": "ADMIN"},
    )
    assert resp_admin.status_code == 200
    assert resp_admin.json()["overallStatus"] == "IDLE"

    # In dev mode, regular user receives default identity
    resp_search = client.post(
        "/api/v1/search",
        json={"query": "test query"},
    )
    assert resp_search.status_code == 200
