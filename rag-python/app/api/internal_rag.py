"""Internal endpoints called by backend-java.

This module provides internal service-to-service endpoints under /internal/v1.
In Phase 1, search is a contract stub that echoes identity and query metadata.
Actual lexical and vector retrieval is implemented in Phase 3.
"""

import logging

from fastapi import APIRouter

from app.common.config import get_settings
from app.contracts.rag_health import RagHealthRequest, RagHealthResponse
from app.contracts.rag_search import RagSearchRequest, RagSearchResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.post("/rag/health", response_model=RagHealthResponse)
def rag_health(request: RagHealthRequest) -> RagHealthResponse:
    """Echo a contract health check back to backend-java."""
    settings = get_settings()
    logger.info("rag_health_contract_call requested_by=%s", request.requested_by)
    return RagHealthResponse(
        status="ok",
        service=settings.app_name,
        contract_version=settings.contract_version,
        message="contract stub alive",
    )


@router.post("/rag/search", response_model=RagSearchResponse)
def rag_search(request: RagSearchRequest) -> RagSearchResponse:
    """Internal search stub called by backend-java.

    Validates that user context (userId, groupIds) and query are properly passed
    across the service boundary. Actual retrieval is implemented in Phase 3.
    """
    logger.info(
        "rag_search_contract_call user_id=%s group_ids=%s query=%s limit=%s source_types=%s",
        request.user_id,
        request.group_ids,
        request.query,
        request.limit,
        request.source_types,
    )
    return RagSearchResponse(
        status="ok",
        query=request.query,
        total_results=0,
        results=[],
    )
