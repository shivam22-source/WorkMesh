"""Public REST API v1 for WorkMesh Enterprise Knowledge & Context Platform.

Consolidates search, ask, and administrative endpoints previously split between
backend-java and rag-python into a unified, high-performance FastAPI service.
"""

import logging
import time
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from app.api.concurrency import ConcurrencyLimitExceededError, search_concurrency_limiter
from app.auth.user_context import AccessDeniedError, UserContext, get_current_user, require_admin
from app.common.config import get_settings
from app.contracts.rag_ask import RagAskRequest
from app.dependencies import (
    get_grounded_rag_service,
    get_hybrid_retriever,
    get_repository,
)
from app.indexing.models import SyncStateRecord
from app.indexing.repository import KnowledgeRepository
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["public_v1"])


# ---------------------------------------------------------------------------
# Search DTOs
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = Field(default=10, ge=1, le=100)
    sourceTypes: Optional[List[str]] = None
    source_types: Optional[List[str]] = None
    userId: Optional[str] = None
    groupIds: Optional[List[str]] = None

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("query must not be blank")
        return v

    @property
    def resolved_source_types(self) -> Optional[List[str]]:
        return self.sourceTypes or self.source_types

    @property
    def resolved_limit(self) -> int:
        return self.limit if self.limit is not None else 10


class SearchResultItem(BaseModel):
    chunkId: str
    documentId: str
    sourceType: str
    title: str
    snippet: str
    sourceUrl: str
    author: Optional[str] = None
    score: float


class StageTimings(BaseModel):
    lexicalMs: float = 0.0
    vectorMs: float = 0.0
    fuseMs: float = 0.0
    graphMs: float = 0.0
    rerankMs: float = 0.0


class SearchResponse(BaseModel):
    query: str
    totalResults: int
    results: List[SearchResultItem]
    searchTimeMs: int
    status: str = "SUCCESS"
    timings: Optional[StageTimings] = None


# ---------------------------------------------------------------------------
# Ask DTOs
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str
    sourceTypes: Optional[List[str]] = None
    source_types: Optional[List[str]] = None
    userId: Optional[str] = None
    groupIds: Optional[List[str]] = None

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("question must not be blank")
        return v

    @property
    def resolved_source_types(self) -> Optional[List[str]]:
        return self.sourceTypes or self.source_types


class CitationItem(BaseModel):
    sourceType: str
    title: str
    url: str
    snippet: str


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: List[CitationItem]
    confidence: str
    status: str


# ---------------------------------------------------------------------------
# Sync & Audit DTOs
# ---------------------------------------------------------------------------

class SourceSyncStatus(BaseModel):
    sourceType: str
    status: str
    cursor: Optional[str] = None
    lastSyncStartedAt: Optional[str] = None
    lastSyncCompletedAt: Optional[str] = None
    recordsSyncedLastRun: int = 0
    errorMessage: Optional[str] = None


class SyncStatusResponse(BaseModel):
    overallStatus: str
    sources: List[SourceSyncStatus]


class AuditEventResponse(BaseModel):
    id: Optional[int] = None
    userId: str
    action: str
    resource: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ipAddress: Optional[str] = None
    timestamp: Optional[str] = None


class SyncResetRequest(BaseModel):
    sourceType: str = Field(
        default="ALL",
        description="Connector source type to reset: GITHUB, SLACK, EMAIL, or ALL",
    )


class SyncResetResponse(BaseModel):
    sourceType: str
    status: str = "RESET"
    message: str
    resetSources: List[str]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _record_audit_safe(
    repo: KnowledgeRepository,
    user_id: str,
    action: str,
    resource: str,
    details: Dict[str, Any],
    ip_address: Optional[str] = None,
) -> None:
    """Record an audit event fail-open; errors are logged without aborting."""
    try:
        repo.record_audit_event(
            user_id=user_id,
            action=action,
            resource=resource,
            details=details,
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.warning(
            "audit_logging_failed user_id=%s action=%s err=%s",
            user_id,
            action,
            exc,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest,
    req: Request,
    user: Annotated[UserContext, Depends(get_current_user)],
    retriever: Annotated[HybridRetriever, Depends(get_hybrid_retriever)],
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> SearchResponse:
    """Execute permission-aware hybrid search across indexed enterprise knowledge."""
    if not search_concurrency_limiter.acquire():
        raise ConcurrencyLimitExceededError(
            retry_after=get_settings().search_retry_after_seconds
        )

    try:
        start_time = time.perf_counter()
        client_ip = req.client.host if req.client else None

        logger.info(
            "search_initiated user_id=%s groups=%s query='%s'",
            user.user_id,
            user.group_ids,
            request.query,
        )

        _record_audit_safe(
            repo=repo,
            user_id=user.user_id,
            action="SEARCH",
            resource="knowledge_index",
            details={"query": request.query, "limit": request.resolved_limit},
            ip_address=client_ip,
        )

        results = retriever.search(
            query=request.query,
            limit=request.resolved_limit,
            source_types=request.resolved_source_types,
            user_id=user.user_id,
            group_ids=list(user.group_ids),
        )

        items = [
            SearchResultItem(
                chunkId=r.chunk_id,
                documentId=r.document_id,
                sourceType=r.source_type,
                title=r.title,
                snippet=r.snippet,
                sourceUrl=r.source_url,
                author=r.author,
                score=r.score,
            )
            for r in results
        ]

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        raw_timings = getattr(retriever, "last_stage_timings", None)
        stage_timings = StageTimings(**raw_timings) if raw_timings else None

        return SearchResponse(
            query=request.query,
            totalResults=len(items),
            results=items,
            searchTimeMs=elapsed_ms,
            status="SUCCESS",
            timings=stage_timings,
        )
    finally:
        search_concurrency_limiter.release()


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    req: Request,
    user: Annotated[UserContext, Depends(get_current_user)],
    rag_service: Annotated[GroundedRagService, Depends(get_grounded_rag_service)],
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> AskResponse:
    """Execute grounded question answering with verifiable citations."""
    if not search_concurrency_limiter.acquire():
        raise ConcurrencyLimitExceededError(
            retry_after=get_settings().search_retry_after_seconds
        )

    try:
        client_ip = req.client.host if req.client else None

        logger.info(
            "ask_initiated user_id=%s question='%s'",
            user.user_id,
            request.question,
        )

        _record_audit_safe(
            repo=repo,
            user_id=user.user_id,
            action="ASK",
            resource="knowledge_assistant",
            details={"question": request.question},
            ip_address=client_ip,
        )

        rag_request = RagAskRequest(
            question=request.question,
            user_id=user.user_id,
            group_ids=list(user.group_ids),
            source_types=request.resolved_source_types,
        )

        rag_response = rag_service.ask(rag_request)

        citations = [
            CitationItem(
                sourceType=c.source_type,
                title=c.title,
                url=c.url,
                snippet=c.snippet,
            )
            for c in (rag_response.citations or [])
        ]

        return AskResponse(
            question=rag_response.question,
            answer=rag_response.answer,
            citations=citations,
            confidence=rag_response.confidence,
            status=rag_response.status,
        )
    finally:
        search_concurrency_limiter.release()


def _get_sync_status_common(
    req: Request,
    user: UserContext,
    repo: KnowledgeRepository,
) -> SyncStatusResponse:
    if user.role.upper() != "ADMIN":
        logger.warning(
            "sync_status_forbidden user_id=%s role=%s",
            user.user_id,
            user.role,
        )
        raise AccessDeniedError("Access denied: ADMIN role required to view sync status")

    client_ip = req.client.host if req.client else None
    _record_audit_safe(
        repo=repo,
        user_id=user.user_id,
        action="SYNC_STATUS",
        resource="sync_state",
        details={},
        ip_address=client_ip,
    )

    sources: List[SourceSyncStatus] = []
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
                SourceSyncStatus(
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
                SourceSyncStatus(
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

    return SyncStatusResponse(overallStatus=overall, sources=sources)


@router.get("/sync/status", response_model=SyncStatusResponse)
def get_sync_status(
    req: Request,
    user: Annotated[UserContext, Depends(get_current_user)],
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> SyncStatusResponse:
    """Return status of all connectors for administrators."""
    return _get_sync_status_common(req, user, repo)


@router.get("/admin/sync/status", response_model=SyncStatusResponse)
def get_admin_sync_status(
    req: Request,
    user: Annotated[UserContext, Depends(get_current_user)],
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> SyncStatusResponse:
    """Return status of all connectors for administrators (aliased path)."""
    return _get_sync_status_common(req, user, repo)


@router.get("/admin/audit/events", response_model=List[AuditEventResponse])
def get_audit_events(
    user: Annotated[UserContext, Depends(get_current_user)],
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
    userId: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=1000),
) -> List[AuditEventResponse]:
    """Retrieve audit events for administrators."""
    if user.role.upper() != "ADMIN":
        logger.warning(
            "audit_events_forbidden user_id=%s role=%s",
            user.user_id,
            user.role,
        )
        raise AccessDeniedError("Access denied: ADMIN role required to view audit events")

    effective_user_id = userId or user_id
    raw_events = repo.get_audit_events(
        user_id=effective_user_id,
        action=action,
        limit=limit,
    )

    return [AuditEventResponse(**e) for e in raw_events]


@router.post("/admin/sync/reset", response_model=SyncResetResponse)
def reset_sync_state(
    request: SyncResetRequest,
    req: Request,
    user: Annotated[UserContext, Depends(require_admin)],
    repo: Annotated[KnowledgeRepository, Depends(get_repository)],
) -> SyncResetResponse:
    """Reset connector sync state and clear stale leases (requires ADMIN role)."""
    target = request.sourceType.strip().upper()
    valid_sources = ["GITHUB", "SLACK", "EMAIL"]
    if target == "ALL":
        to_reset = valid_sources
    elif target in valid_sources:
        to_reset = [target]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sourceType '{request.sourceType}'. Must be one of: ALL, GITHUB, SLACK, EMAIL",
        )

    client_ip = req.client.host if req.client else None
    _record_audit_safe(
        repo=repo,
        user_id=user.user_id,
        action="SYNC_RESET",
        resource=f"sync_state:{target}",
        details={"sourceType": target, "resetSources": to_reset},
        ip_address=client_ip,
    )

    for src in to_reset:
        existing = repo.get_sync_state(src)
        cursor = existing.cursor_value if existing else None
        repo.update_sync_state(
            SyncStateRecord(
                source_type=src,
                cursor_value=cursor,
                status="IDLE",
                last_sync_started_at=None,
                last_sync_completed_at=None,
                records_synced_last_run=0,
                error_message=None,
            )
        )

    logger.info("sync_state_reset user_id=%s sources=%s", user.user_id, to_reset)
    return SyncResetResponse(
        sourceType=target,
        status="RESET",
        message=f"Sync state reset to IDLE for {', '.join(to_reset)}",
        resetSources=to_reset,
    )
