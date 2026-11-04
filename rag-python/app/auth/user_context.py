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
    """Decode and validate a signed JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp"]},
        )
    except jwt.ExpiredSignatureError:
        logger.warning("jwt_token_expired")
        raise AuthenticationRequiredError("Token has expired")
    except jwt.InvalidTokenError as exc:
        logger.warning("jwt_token_invalid err=%s", exc)
        raise AuthenticationRequiredError("Invalid token signature or payload")

    user_id = str(payload.get("sub") or payload.get("userId") or payload.get("user_id") or "").strip()
    if not user_id:
        raise AuthenticationRequiredError("Token claims missing required user identifier ('sub')")

    role = str(payload.get("role") or DEFAULT_ROLE).strip().upper()
    groups_claim = payload.get("groups") or payload.get("groupIds") or []
    if isinstance(groups_claim, str):
        group_ids = {g.strip() for g in groups_claim.split(",") if g.strip()}
    elif isinstance(groups_claim, (list, tuple, set)):
        group_ids = {str(g).strip() for g in groups_claim if str(g).strip()}
    else:
        group_ids = set()

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
