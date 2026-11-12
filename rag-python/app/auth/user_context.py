"""Deterministic and JWT-based user context provider for WorkMesh.

Supports two authentication modes:
- "prod" (default): Strict fail-closed JWT authentication via PyJWT. Rejects
  header-based identity forging (X-User-Id, X-User-Role, X-User-Groups).
- "dev": Header-based simulation allowing deterministic testing and local debugging,
  with fallback to employee_42.
"""

from dataclasses import dataclass, field
import logging
from typing import Annotated, Any, Dict, Optional, Set
import jwt
from fastapi import Depends, Header, Request

from app.common.config import Settings, get_settings

logger = logging.getLogger(__name__)


class AccessDeniedError(Exception):
    """Raised when an operation is forbidden due to role or permission restrictions (403)."""

    def __init__(self, message: str = "Access denied"):
        super().__init__(message)
        self.message = message


class AuthenticationRequiredError(Exception):
    """Raised when authentication credentials are missing, invalid, or forged in prod mode (401)."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class UserContext:
    user_id: str
    email: str
    name: str
    role: str
    group_ids: Set[str] = field(default_factory=set)


DEFAULT_USER_ID = "employee_42"
DEFAULT_EMAIL = "employee_42@company.internal"
DEFAULT_NAME = "Alex Engineer"
DEFAULT_ROLE = "ENGINEER"
DEFAULT_GROUPS = {"group_engineering", "group_backend"}


def _decode_jwt_token(token: str, settings: Settings) -> UserContext:
    """Decode and validate a signed JWT token against explicit algorithms and TTL bounds."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        logger.warning("jwt_header_invalid err=%s", exc)
        raise AuthenticationRequiredError("Invalid token header")

    alg = str(header.get("alg") or "").strip()
    if not alg or alg.lower() == "none" or alg not in settings.allowed_jwt_algorithms:
        logger.warning("jwt_algorithm_rejected alg=%s allowed=%s", alg, settings.allowed_jwt_algorithms)
        raise AuthenticationRequiredError("Unsupported or disallowed JWT signing algorithm")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=settings.allowed_jwt_algorithms,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        logger.warning("jwt_token_expired")
        raise AuthenticationRequiredError("Token has expired")
    except jwt.MissingRequiredClaimError as exc:
        logger.warning("jwt_missing_required_claim err=%s", exc)
        raise AuthenticationRequiredError(f"Token missing required claim: {exc.claim}")
    except jwt.InvalidTokenError as exc:
        logger.warning("jwt_token_invalid err=%s", exc)
        raise AuthenticationRequiredError("Invalid token signature or payload")

    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise AuthenticationRequiredError("Token claims missing required user identifier ('sub')")

    # Enforce JWT_MAX_TTL_SECONDS using (exp - iat) when iat is present
    exp_val = payload.get("exp")
    iat_val = payload.get("iat")
    if not isinstance(exp_val, (int, float)):
        raise AuthenticationRequiredError("Token 'exp' claim must be numeric")
    if iat_val is not None:
        if not isinstance(iat_val, (int, float)):
            raise AuthenticationRequiredError("Token 'iat' claim must be numeric")
        if (exp_val - iat_val) > settings.jwt_max_ttl_seconds:
            logger.warning(
                "jwt_ttl_exceeded ttl=%s max_ttl=%s",
                exp_val - iat_val,
                settings.jwt_max_ttl_seconds,
            )
            raise AuthenticationRequiredError(
                f"Token lifetime exceeds JWT_MAX_TTL_SECONDS ({settings.jwt_max_ttl_seconds}s)"
            )

    role = str(payload.get("role") or DEFAULT_ROLE).strip().upper()
    if "groups" in payload and payload["groups"] is not None:
        groups_claim = payload["groups"]
    elif "groupIds" in payload and payload["groupIds"] is not None:
        groups_claim = payload["groupIds"]
    else:
        groups_claim = []

    if not isinstance(groups_claim, list) or not all(isinstance(g, str) for g in groups_claim):
        logger.warning("jwt_invalid_groups_claim type=%s", type(groups_claim).__name__)
        raise AuthenticationRequiredError("Token 'groups' claim must be a list of strings")

    group_ids = {g.strip() for g in groups_claim if g.strip()}

    email = str(payload.get("email") or f"{user_id}@company.internal")
    name = str(payload.get("name") or f"User ({user_id})")

    return UserContext(
        user_id=user_id,
        email=email,
        name=name,
        role=role,
        group_ids=group_ids,
    )


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
    x_user_groups: Optional[str] = Header(None, alias="X-User-Groups"),
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> UserContext:
    """Resolve authenticated user context according to AUTH_MODE."""
    if settings is None:
        settings = get_settings()

    if settings.is_prod:
        # In prod mode, completely reject any X-User-* simulation headers
        has_sim_headers = bool(
            (x_user_id and x_user_id.strip())
            or (x_user_role and x_user_role.strip())
            or (x_user_groups and x_user_groups.strip())
        )
        if has_sim_headers:
            logger.warning("forged_identity_headers_rejected_in_prod path=%s", request.url.path)
            raise AuthenticationRequiredError("Header-based authentication is forbidden in production mode")

        # Identity MUST come from a signed Bearer JWT
        if not authorization or not authorization.strip():
            logger.warning("missing_authorization_header path=%s", request.url.path)
            raise AuthenticationRequiredError("Missing Authorization header")

        parts = authorization.strip().split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise AuthenticationRequiredError("Invalid Authorization header format. Expected 'Bearer <token>'")

        return _decode_jwt_token(parts[1], settings)

    # Dev mode: Allow JWT if present, otherwise allow headers, otherwise default to employee_42
    if authorization and authorization.strip().lower().startswith("bearer "):
        parts = authorization.strip().split()
        if len(parts) == 2:
            try:
                return _decode_jwt_token(parts[1], settings)
            except AuthenticationRequiredError:
                pass  # Fall through to header resolution in dev mode

    clean_id = x_user_id.strip() if x_user_id and x_user_id.strip() else DEFAULT_USER_ID
    clean_role = x_user_role.strip().upper() if x_user_role and x_user_role.strip() else None

    if x_user_groups is not None:
        groups = {g.strip() for g in x_user_groups.split(",") if g.strip()}
    else:
        groups = set(DEFAULT_GROUPS)

    if clean_id.lower() == "employee_admin":
        return UserContext(
            user_id="employee_admin",
            email="admin@company.internal",
            name="Sam Admin",
            role=clean_role or "ADMIN",
            group_ids=groups if x_user_groups is not None else {"group_engineering"},
        )

    return UserContext(
        user_id=clean_id,
        email=f"{clean_id}@company.internal",
        name=f"Test User ({clean_id})",
        role=clean_role or DEFAULT_ROLE,
        group_ids=groups,
    )


def require_admin(
    user: Annotated[UserContext, Depends(get_current_user)],
) -> UserContext:
    """Ensure the current user holds the ADMIN role."""
    if user.role.upper() != "ADMIN":
        logger.warning(
            "access_denied_admin_required user_id=%s role=%s",
            user.user_id,
            user.role,
        )
        raise AccessDeniedError("Access denied: ADMIN role required")
    return user
