"""JWT creation and decoding helpers for WorkMesh production authentication."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt

from app.common.config import get_settings


def create_jwt_token(
    user_id: str,
    role: str = "ENGINEER",
    groups: Optional[List[str]] = None,
    secret: Optional[str] = None,
    expires_in_seconds: int = 3600,
    algorithm: Optional[str] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Create a signed JWT token containing user identity, role, and group claims."""
    sec = secret
    algo = algorithm or "HS256"
    if not sec:
        settings = get_settings()
        sec = sec or settings.jwt_secret
        algo = algorithm or settings.jwt_algorithm
    now = datetime.now(timezone.utc)
    claims: Dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "groups": groups or [],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, sec, algorithm=algo)
