"""Liveness and readiness probes for WorkMesh API service.

- /health is liveness: the process is running.
- /ready is readiness: verifies PostgreSQL connectivity.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.common.config import get_settings
from app.contracts.errors import ErrorResponse
from app.contracts.rag_health import LivenessResponse, ReadinessResponse
from app.dependencies import get_repository
from app.indexing.repository import KnowledgeRepository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Verifies that the FastAPI process is running without querying external dependencies.",
)
def health() -> LivenessResponse:
    """Liveness probe. Must never depend on Postgres or any other service."""
    settings = get_settings()
    return LivenessResponse(status="ok", service=settings.app_name)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Verifies PostgreSQL connectivity before accepting live traffic.",
    responses={503: {"model": ErrorResponse, "description": "Database dependency unavailable"}},
)
def ready(
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> ReadinessResponse:
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
    return ReadinessResponse(status="ok", service=settings.app_name, database="ok")
