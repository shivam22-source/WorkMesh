"""Internal endpoints called by backend-java.

This is a stub in Phase 0. Its only job is to prove that both services agree
on a wire format and that the Java client can reach Python over HTTP.

Retrieval, reranking and LLM synthesis are Phase 3 and Phase 4.
"""

import logging

from fastapi import APIRouter

from app.common.config import get_settings
from app.contracts.rag_health import RagHealthRequest, RagHealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/v1", tags=["internal"])


@router.post("/rag/health", response_model=RagHealthResponse)
def rag_health(request: RagHealthRequest) -> RagHealthResponse:
    """Echo a contract health check back to backend-java.

    Request validation is handled by Pydantic: a body with missing or extra
    fields is rejected with 422 before this function runs.
    """
    settings = get_settings()
    logger.info("rag_health_contract_call requested_by=%s", request.requested_by)
    return RagHealthResponse(
        status="ok",
        service=settings.app_name,
        contract_version=settings.contract_version,
        message="contract stub alive",
    )