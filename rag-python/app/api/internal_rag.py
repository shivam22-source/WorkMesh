"""Internal endpoints called by backend-java.

This module provides internal service-to-service endpoints under /internal/v1.
In Phase 1, search is a contract stub that echoes identity and query metadata.
Actual lexical and vector retrieval is implemented in Phase 3.
"""

from functools import lru_cache
import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from app.common.config import get_settings
from app.contracts.rag_health import RagHealthRequest, RagHealthResponse
from app.contracts.rag_search import RagSearchRequest, RagSearchResponse
from app.indexing.repository import KnowledgeRepository, PostgresKnowledgeRepository
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/v1", tags=["internal"])


@lru_cache(maxsize=1)
def get_repository() -> KnowledgeRepository:
    settings = get_settings()
    return PostgresKnowledgeRepository(connection_url=settings.database_url)


@lru_cache(maxsize=1)
def get_hybrid_retriever() -> HybridRetriever:
    repo = get_repository()
    return HybridRetriever(repository=repo)


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
def rag_search(
    request: RagSearchRequest,
    retriever: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
) -> RagSearchResponse:
    """Internal search called by backend-java.

    Executes hybrid retrieval across indexed knowledge.
    User context (userId, groupIds) is preserved and logged for Phase 4 ACL enforcement.
    """
    logger.info(
        "rag_search_call user_id=%s group_ids=%s query=%s limit=%s source_types=%s",
        request.user_id,
        request.group_ids,
        request.query,
        request.limit,
        request.source_types,
    )
    results = retriever.search(
        query=request.query,
        limit=request.limit,
        source_types=request.source_types,
    )
    return RagSearchResponse(
        status="ok",
        query=request.query,
        total_results=len(results),
        results=results,
    )
