#!/usr/bin/env python3
r"""Generate a signed JWT token for authenticating against WorkMesh in prod mode.

Usage:
  Linux/macOS:
    JWT_SECRET="your-32+-char-secret" python scripts/make_token.py --user-id employee_42 --role ENGINEER --groups group_engineering,group_backend --ttl 3600

  Windows (PowerShell):
    $env:JWT_SECRET="your-32+-char-secret"; rag-python\.venv\Scripts\python.exe scripts\make_token.py --user-id employee_42 --role ENGINEER --groups group_engineering,group_backend --ttl 3600
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    import jwt
except ImportError as exc:  # pragma: no cover
    print(
        "Error: PyJWT is required. Run with the rag-python virtualenv "
        "(e.g. rag-python/.venv/bin/python or rag-python\\.venv\\Scripts\\python.exe).",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def build_token(
    user_id: str,
    role: str,
    groups: list[str],
    ttl_seconds: int,
    secret: str,
    algorithm: str = "HS256",
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "groups": groups,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mint a signed WorkMesh JWT bearer token.")
    parser.add_argument("--user-id", default="employee_42", help="Subject user ID claim (sub)")
    parser.add_argument("--role", default="ENGINEER", help="User role claim (e.g. ENGINEER, ADMIN)")
    parser.add_argument(
        "--groups",
        default="group_engineering,group_backend",
        help="Comma-separated authorized group IDs (default: group_engineering,group_backend). Pass '' for none.",
    )
    parser.add_argument("--ttl", type=int, default=3600, help="Token lifetime in seconds (default: 3600)")
    parser.add_argument("--secret", default=None, help="Signing secret (defaults to JWT_SECRET env var)")
    parser.add_argument("--algorithm", default=None, help="JWT algorithm (defaults to JWT_ALGORITHM env var or HS256)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    secret = args.secret or os.environ.get("JWT_SECRET")
    if not secret:
        print(
            "Error: signing secret missing. Set JWT_SECRET env var or pass --secret.",
            file=sys.stderr,
        )
        return 1

    algorithm = args.algorithm or os.environ.get("JWT_ALGORITHM", "HS256")
    groups = [g.strip() for g in args.groups.split(",") if g.strip()] if args.groups else []
    token = build_token(
        user_id=args.user_id,
        role=args.role,
        groups=groups,
        ttl_seconds=args.ttl,
        secret=secret,
        algorithm=algorithm,
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
