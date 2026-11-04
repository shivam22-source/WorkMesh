"""Deterministic user context provider for WorkMesh.

Provides employee_42 (Alex Engineer, Engineering & Backend groups) by default
unless an optional X-User-Id header is passed to simulate another identity
(e.g. employee_admin or a custom test user).
"""

from dataclasses import dataclass, field
import logging
from typing import Annotated, Optional, Set

from fastapi import Depends, Header

logger = logging.getLogger(__name__)


class AccessDeniedError(Exception):
    """Raised when an operation is forbidden due to role or permission restrictions."""

    def __init__(self, message: str = "Access denied"):
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


def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_user_role: Optional[str] = Header(None, alias="X-User-Role"),
    x_user_groups: Optional[str] = Header(None, alias="X-User-Groups"),
) -> UserContext:
    """Deterministic authentication provider for development, integration, and testing.

    Provides employee_42 unless optional X-User-Id, X-User-Role, or X-User-Groups
    headers are passed to simulate different tenant principals.
    """
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
