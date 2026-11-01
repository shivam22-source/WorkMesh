"""Internal endpoints called by backend-java.

This module provides internal service-to-service endpoints under /internal/v1.
In Phase 1, search is a contract stub that echoes identity and query metadata.
Actual lexical and vector retrieval is implemented in Phase 3.
"""

from functools import lru_cache
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.common.config import get_settings
from app.contracts.rag_ask import RagAskRequest, RagAskResponse
from app.contracts.rag_health import RagHealthRequest, RagHealthResponse
from app.contracts.rag_search import RagSearchRequest, RagSearchResponse
from app.indexing.repository import KnowledgeRepository, PostgresKnowledgeRepository
from app.rag.service import GroundedRagService
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


@lru_cache(maxsize=1)
def get_grounded_rag_service() -> GroundedRagService:
    retriever = get_hybrid_retriever()
    return GroundedRagService(retriever=retriever)


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
        user_id=request.user_id,
        group_ids=request.group_ids,
    )
    return RagSearchResponse(
        status="ok",
        query=request.query,
        total_results=len(results),
        results=results,
    )


@router.post("/rag/ask", response_model=RagAskResponse)
def rag_ask(
    request: RagAskRequest,
    rag_service: Annotated[GroundedRagService, Depends(get_grounded_rag_service)],
) -> RagAskResponse:
    """Internal Grounded RAG ask endpoint called by backend-java.

    Executes permission-filtered retrieval, deterministic reranking, evidence assembly,
    grounded LLM synthesis, and citation mapping.
    """
    logger.info(
        "rag_ask_call user_id=%s group_ids=%s question='%s' source_types=%s",
        request.user_id,
        request.group_ids,
        request.question,
        request.source_types,
    )
    return rag_service.ask(request)


# ---------------------------------------------------------------------------
# Sync Status & Audit Models and Endpoints (Phase 5 Done Criteria)
# ---------------------------------------------------------------------------

class SourceSyncStatusModel(BaseModel):
    sourceType: str
    status: str
    cursor: Optional[str] = None
    lastSyncStartedAt: Optional[str] = None
    lastSyncCompletedAt: Optional[str] = None
    recordsSyncedLastRun: int = 0
    errorMessage: Optional[str] = None


class SyncStatusResponseModel(BaseModel):
    overallStatus: str
    sources: List[SourceSyncStatusModel]


class AuditEventCreateRequest(BaseModel):
    userId: Optional[str] = None
    user_id: Optional[str] = None
    action: str
    resource: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ipAddress: Optional[str] = None
    ip_address: Optional[str] = None

    @property
    def resolved_user_id(self) -> str:
        uid = self.userId or self.user_id
        if not uid:
            raise ValueError("userId or user_id is required")
        return uid

    @property
    def resolved_ip_address(self) -> Optional[str]:
        return self.ipAddress or self.ip_address


class AuditEventItemModel(BaseModel):
    id: Optional[int] = None
    userId: str
    action: str
    resource: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ipAddress: Optional[str] = None
    timestamp: Optional[str] = None


@router.get("/sync/status", response_model=SyncStatusResponseModel)
def get_sync_status(
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> SyncStatusResponseModel:
    """Return status of all connectors and derive overall status."""
    sources: List[SourceSyncStatusModel] = []
    for source in ["GITHUB", "SLACK", "EMAIL"]:
        state = repo.get_sync_state(source)
        if state:
            started = (
                state.last_sync_started_at.isoformat()
                if state.last_sync_started_at
                else None
            )
            completed = (
                state.last_sync_completed_at.isoformat()
                if state.last_sync_completed_at
                else None
            )
            sources.append(
                SourceSyncStatusModel(
                    sourceType=state.source_type,
                    status=state.status or "IDLE",
                    cursor=state.cursor_value,
                    lastSyncStartedAt=started,
                    lastSyncCompletedAt=completed,
                    recordsSyncedLastRun=state.records_synced_last_run or 0,
                    errorMessage=state.error_message,
                )
            )
        else:
            sources.append(
                SourceSyncStatusModel(
                    sourceType=source,
                    status="IDLE",
                    cursor=None,
                    lastSyncStartedAt=None,
                    lastSyncCompletedAt=None,
                    recordsSyncedLastRun=0,
                    errorMessage=None,
                )
            )

    statuses = [s.status for s in sources]
    if any(s == "FAILED" for s in statuses):
        overall = "FAILED"
    elif any(s in ("RUNNING", "IN_PROGRESS", "SYNCING") for s in statuses):
        overall = "RUNNING"
    else:
        overall = "IDLE"

    return SyncStatusResponseModel(overallStatus=overall, sources=sources)


@router.post("/audit/events")
def record_audit_event(
    request: AuditEventCreateRequest,
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> Dict[str, str]:
    """Persist an audit event to the durable audit store."""
    repo.record_audit_event(
        user_id=request.resolved_user_id,
        action=request.action,
        resource=request.resource,
        details=request.details,
        ip_address=request.resolved_ip_address,
    )
    return {"status": "ok"}


@router.get("/audit/events", response_model=List[AuditEventItemModel])
def get_audit_events(
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
    userId: Optional[str] = None,
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
) -> List[AuditEventItemModel]:
    """Retrieve recent audit events ordered by timestamp descending."""
    effective_user_id = userId or user_id
    events = repo.get_audit_events(
        user_id=effective_user_id, action=action, limit=limit
    )
    return [AuditEventItemModel(**e) for e in events]

