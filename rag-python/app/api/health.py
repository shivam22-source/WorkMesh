"""Liveness and readiness probes for WorkMesh API service.

- /health is liveness: the process is running.
- /ready is readiness: verifies PostgreSQL connectivity.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.common.config import get_settings
from app.contracts.rag_health import ServiceHealth
from app.dependencies import get_repository
from app.indexing.repository import KnowledgeRepository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=ServiceHealth)
def health() -> ServiceHealth:
    """Liveness probe. Must never depend on Postgres or any other service."""
    settings = get_settings()
    return ServiceHealth(status="ok", service=settings.app_name)


@router.get("/ready", response_model=ServiceHealth)
def ready(
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> ServiceHealth:
    """Readiness probe. Verifies PostgreSQL connectivity."""
    settings = get_settings()
    try:
        repo.check_health()
    except Exception as exc:
        logger.error("readiness_check_failed err=%s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database service is unavailable",
        ) from exc
    return ServiceHealth(status="ok", service=settings.app_name)
