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
) -> UserContext:
    """Deterministic authentication provider for development and testing.

    Always provides employee_42 unless an optional X-User-Id header is passed.
    """
    if x_user_id and x_user_id.strip():
        clean_id = x_user_id.strip()
        if clean_id.lower() == "employee_admin":
            return UserContext(
                user_id="employee_admin",
                email="admin@company.internal",
                name="Sam Admin",
                role="ADMIN",
                group_ids={"group_engineering"},
            )
        return UserContext(
            user_id=clean_id,
            email=f"{clean_id}@company.internal",
            name=f"Test User ({clean_id})",
            role=DEFAULT_ROLE,
            group_ids=set(DEFAULT_GROUPS),
        )

    return UserContext(
        user_id=DEFAULT_USER_ID,
        email=DEFAULT_EMAIL,
        name=DEFAULT_NAME,
        role=DEFAULT_ROLE,
        group_ids=set(DEFAULT_GROUPS),
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
