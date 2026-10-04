"""Liveness and readiness for rag-python.

Phase 0 distinction:
  - /health is liveness: the process is up and can serve requests.
  - /ready is readiness: the process is able to do real work.

In Phase 0 there is no database connection, so /ready reports ok without
checking anything. Phase 1 must make /ready actually verify Postgres, and that
change is called out in docs/api/java-python-contract.md.
"""

import logging

from fastapi import APIRouter

from app.common.config import get_settings
from app.contracts.rag_health import ServiceHealth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=ServiceHealth)
def health() -> ServiceHealth:
    """Liveness probe. Must never depend on Postgres or any other service."""
    settings = get_settings()
    return ServiceHealth(status="ok", service=settings.app_name)


@router.get("/ready", response_model=ServiceHealth)
def ready() -> ServiceHealth:
    """Readiness probe. Phase 0: no dependency check yet, see module docstring."""
    settings = get_settings()
    logger.debug("readiness_check dependencies=none phase=0")
    return ServiceHealth(status="ok", service=settings.app_name)