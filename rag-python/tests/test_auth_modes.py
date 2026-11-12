"""Tests for authentication modes: production JWT verification vs dev header simulation."""

import time

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_utils import create_jwt_token
from app.common.config import DEFAULT_DEV_JWT_SECRET, Settings, get_settings
from app.dependencies import get_hybrid_retriever, get_repository
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.retrieval.hybrid import HybridRetriever

STRONG_PROD_SECRET = "production_super_strong_secret_key_exceeding_32_characters"


@pytest.fixture
def repo() -> InMemoryKnowledgeRepository:
    return InMemoryKnowledgeRepository()


@pytest.fixture
def retriever(repo: InMemoryKnowledgeRepository) -> HybridRetriever:
    return HybridRetriever(repository=repo)


def test_prod_mode_rejects_forged_role_header(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, any simulation headers (X-User-*) are strictly rejected with 401."""
    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
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
    assert "forbidden in production mode" in resp.json()["error"]["message"]


def test_prod_mode_rejects_missing_jwt(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, requests lacking an Authorization Bearer token fail closed with 401."""
    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
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
    assert "Missing Authorization header" in resp.json()["error"]["message"]


def test_prod_mode_accepts_valid_jwt(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, a properly signed and non-expired JWT is accepted."""
    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
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
    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
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
    assert "Token has expired" in resp.json()["error"]["message"]


def test_prod_mode_rejects_tampered_jwt(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, a JWT signed with a different key or tampered signature is rejected with 401."""
    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
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
    assert "Invalid token signature" in resp.json()["error"]["message"]


def test_prod_mode_require_admin_role_enforcement(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """In prod mode, valid JWT without ADMIN role receives 403 Forbidden on admin endpoints."""
    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
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
    assert "ADMIN role required" in resp_forbidden.json()["error"]["message"]

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


def test_prod_mode_default_secret_fails_to_start(monkeypatch):
    """Prod mode with default dev secret must fail startup (raise clear ValueError, app must not boot)."""
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("JWT_SECRET", DEFAULT_DEV_JWT_SECRET)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="cannot use the known dev default"):
        create_app()


def test_prod_mode_unset_secret_fails_to_start(monkeypatch):
    """Prod mode with unset JWT secret must fail startup (app must not boot)."""
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("JWT_SECRET", "")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="JWT_SECRET is required"):
        create_app()


def test_prod_mode_short_secret_fails_to_start(monkeypatch):
    """Prod mode with secret shorter than 32 characters must fail startup."""
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("JWT_SECRET", "too_short_secret_under_32")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="at least 32 characters"):
        create_app()


def test_prod_mode_strong_secret_starts(monkeypatch):
    """Prod mode with a strong 32+ character secret starts up successfully."""
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("JWT_SECRET", STRONG_PROD_SECRET)
    get_settings.cache_clear()
    app = create_app()
    assert app is not None


def test_dev_mode_default_secret_starts_with_warning(monkeypatch, caplog):
    """Dev mode with default secret starts and logs a security warning."""
    import logging

    from app.common.config import DEFAULT_DEV_JWT_SECRET
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("JWT_SECRET", DEFAULT_DEV_JWT_SECRET)
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING):
        app = create_app()
        assert app is not None
        assert any("default JWT secret in dev mode" in record.message for record in caplog.records)


@pytest.mark.parametrize("invalid_mode", ["production", "staging", "", "devv"])
def test_invalid_auth_mode_fails_to_start(monkeypatch, invalid_mode):
    """Any AUTH_MODE other than 'prod' or 'dev' must fail startup."""
    monkeypatch.setenv("AUTH_MODE", invalid_mode)
    monkeypatch.setenv("JWT_SECRET", STRONG_PROD_SECRET)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="Invalid AUTH_MODE"):
        create_app()


def test_auth_mode_whitespace_prod_accepted_and_rejects_forged_header(monkeypatch, repo, retriever):
    """' Prod ' is accepted after normalizing, and rejects forged headers."""
    monkeypatch.setenv("AUTH_MODE", " Prod ")
    monkeypatch.setenv("JWT_SECRET", STRONG_PROD_SECRET)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.auth_mode == "prod"
    assert settings.is_prod is True

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    resp = client.get(
        "/api/v1/admin/sync/status",
        headers={"X-User-Role": "ADMIN", "X-User-Id": "forged_admin"},
    )
    assert resp.status_code == 401
    assert "forbidden in production mode" in resp.json()["error"]["message"]


def test_auth_mode_uppercase_dev_accepted_and_normalizes(monkeypatch):
    """'DEV' is accepted after normalizing."""
    monkeypatch.setenv("AUTH_MODE", "DEV")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.auth_mode == "dev"
    assert settings.is_dev is True
    assert settings.is_prod is False


def test_prod_mode_rejects_alg_none_token(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """Unsigned tokens claiming alg=none must always be rejected with 401."""
    import base64
    import json

    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    def _b64(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    now = int(time.time())
    header = _b64({"alg": "none", "typ": "JWT"})
    payload = _b64({"sub": "attacker", "role": "ADMIN", "groups": ["group_finance"], "iat": now, "exp": now + 300})
    forged_none_token = f"{header}.{payload}."

    resp = client.post(
        "/api/v1/search",
        json={"query": "test"},
        headers={"Authorization": f"Bearer {forged_none_token}"},
    )
    assert resp.status_code == 401
    assert "algorithm" in resp.json()["error"]["message"].lower()


def test_config_rejects_alg_none_in_allowlist(monkeypatch):
    """Settings validation rejects 'none' in JWT_ALGORITHM / JWT_ALGORITHMS."""
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("JWT_SECRET", STRONG_PROD_SECRET)
    monkeypatch.setenv("JWT_ALGORITHMS", "HS256,none")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="forbidden"):
        create_app()


def test_prod_mode_rejects_missing_exp_and_missing_sub(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """Tokens missing 'exp' or 'sub' claims must be rejected with 401."""
    import jwt as pyjwt

    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    now = int(time.time())
    no_exp = pyjwt.encode({"sub": "alice", "iat": now, "groups": []}, STRONG_PROD_SECRET, algorithm="HS256")
    resp_no_exp = client.post("/api/v1/search", json={"query": "test"}, headers={"Authorization": f"Bearer {no_exp}"})
    assert resp_no_exp.status_code == 401

    no_sub = pyjwt.encode({"role": "ENGINEER", "iat": now, "exp": now + 300, "groups": []}, STRONG_PROD_SECRET, algorithm="HS256")
    resp_no_sub = client.post("/api/v1/search", json={"query": "test"}, headers={"Authorization": f"Bearer {no_sub}"})
    assert resp_no_sub.status_code == 401


def test_prod_mode_rejects_tampered_groups_payload(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """Modifying the groups claim in a signed JWT without re-signing fails signature verification with 401."""
    import base64
    import json

    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    valid_token = create_jwt_token(
        user_id="bob_eng",
        role="ENGINEER",
        groups=["group_engineering"],
        secret=STRONG_PROD_SECRET,
        expires_in_seconds=600,
    )
    h_b64, p_b64, s_b64 = valid_token.split(".")
    padded = p_b64 + "=" * (-len(p_b64) % 4)
    claims = json.loads(base64.urlsafe_b64decode(padded))
    claims["groups"] = ["group_engineering", "group_finance", "group_security"]
    tampered_payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).rstrip(b"=").decode("ascii")
    tampered_token = f"{h_b64}.{tampered_payload}.{s_b64}"

    resp = client.post(
        "/api/v1/search",
        json={"query": "budget"},
        headers={"Authorization": f"Bearer {tampered_token}"},
    )
    assert resp.status_code == 401
    assert "signature" in resp.json()["error"]["message"].lower()


@pytest.mark.parametrize("bad_groups", ["group_engineering", 123, {"group": "eng"}, ["valid", 99]])
def test_prod_mode_rejects_non_list_groups_claim(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever, bad_groups):
    """Tokens with non-list or non-string-list 'groups' claims must be rejected with 401."""
    import jwt as pyjwt

    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    now = int(time.time())
    token = pyjwt.encode(
        {"sub": "alice", "role": "ENGINEER", "groups": bad_groups, "iat": now, "exp": now + 600},
        STRONG_PROD_SECRET,
        algorithm="HS256",
    )
    resp = client.post("/api/v1/search", json={"query": "test"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert "groups" in resp.json()["error"]["message"].lower()


def test_prod_mode_enforces_jwt_max_ttl_seconds(repo: InMemoryKnowledgeRepository, retriever: HybridRetriever):
    """Tokens with (exp - iat) exceeding JWT_MAX_TTL_SECONDS are rejected with 401."""
    prod_settings = Settings(auth_mode="prod", jwt_secret=STRONG_PROD_SECRET, jwt_max_ttl_seconds=3600)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: prod_settings
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    client = TestClient(app)

    too_long = create_jwt_token(
        user_id="alice",
        role="ENGINEER",
        groups=["group_engineering"],
        secret=STRONG_PROD_SECRET,
        expires_in_seconds=7200,
    )
    resp_reject = client.post("/api/v1/search", json={"query": "test"}, headers={"Authorization": f"Bearer {too_long}"})
    assert resp_reject.status_code == 401
    assert "JWT_MAX_TTL_SECONDS" in resp_reject.json()["error"]["message"]

    within_limit = create_jwt_token(
        user_id="alice",
        role="ENGINEER",
        groups=["group_engineering"],
        secret=STRONG_PROD_SECRET,
        expires_in_seconds=1800,
    )
    resp_ok = client.post("/api/v1/search", json={"query": "test"}, headers={"Authorization": f"Bearer {within_limit}"})
    assert resp_ok.status_code == 200


def test_prod_mode_rejects_env_example_placeholder_secret(monkeypatch):
    """Known placeholder secret from .env.example fails startup in prod mode."""
    monkeypatch.setenv("AUTH_MODE", "prod")
    monkeypatch.setenv("JWT_SECRET", "replace_with_a_secure_random_key_of_at_least_32_characters_for_prod")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="known dev default"):
        create_app()
