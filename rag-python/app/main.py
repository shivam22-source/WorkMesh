"""FastAPI application factory for WorkMesh Enterprise Knowledge & Context Platform.

Consolidates API Gateway orchestration, permission-filtered retrieval, and grounded RAG synthesis.
"""

from datetime import datetime, timezone
from http import HTTPStatus
import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import health, internal_rag, metrics, public_v1
from app.api.metrics import record_request_metric
from app.auth.user_context import AccessDeniedError
from app.common.config import get_settings
from app.indexing.repository import DatabaseUnavailableError


def configure_logging(level: str) -> None:
    """Emit one JSON object per log line for unified observability."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt='{"ts":"%(asctime)s","level":"%(levelname)s",'
            '"logger":"%(name)s","message":"%(message)s"}'
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def _build_api_error(
    status_code: int,
    error_phrase: str,
    message: str,
    path: str,
    trace_id: str,
) -> JSONResponse:
    """Build uniform ApiError payload matching the enterprise API contract."""
    return JSONResponse(
        status_code=status_code,
        content={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status_code,
            "error": error_phrase,
            "message": message,
            "path": path,
            "traceId": trace_id,
        },
    )


TAGS_METADATA = [
    {
        "name": "public_v1",
        "description": "Public enterprise search, grounded Q&A, and administrative management endpoints.",
    },
    {
        "name": "health",
        "description": "Liveness (/health) and readiness (/ready) probes for container orchestration.",
    },
    {
        "name": "metrics",
        "description": "Prometheus-compatible operational metrics and request latency summaries.",
    },
    {
        "name": "internal",
        "description": "Internal contract endpoints for multi-source knowledge retrieval.",
    },
]


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="WorkMesh Platform API",
        version="1.0.0",
        description="Unified Enterprise Knowledge & Context Platform API with permission-aware search and grounded Q&A.",
        openapi_tags=TAGS_METADATA,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # -----------------------------------------------------------------------
    # CORS Configuration
    # -----------------------------------------------------------------------
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id"],
    )

    # -----------------------------------------------------------------------
    # Middleware: Trace ID propagation and metrics recording
    # -----------------------------------------------------------------------
    @application.middleware("http")
    async def trace_id_middleware(request: Request, call_next):
        trace_id = (
            request.headers.get("X-Trace-Id")
            or request.headers.get("X-Request-Id")
            or uuid.uuid4().hex
        )
        request.state.trace_id = trace_id
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        response.headers["X-Trace-Id"] = trace_id
        record_request_metric(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_seconds=duration,
        )
        return response

    # -----------------------------------------------------------------------
    # Routers
    # -----------------------------------------------------------------------
    application.include_router(health.router)
    application.include_router(public_v1.router)
    application.include_router(internal_rag.router)
    application.include_router(metrics.router)

    # -----------------------------------------------------------------------
    # Static Demo Console UI Root
    # -----------------------------------------------------------------------
    possible_ui_paths = [
        Path(__file__).resolve().parent.parent.parent / "demo-ui" / "index.html",
        Path("demo-ui") / "index.html",
        Path("../demo-ui") / "index.html",
    ]
    ui_index_path = next((p for p in possible_ui_paths if p.is_file()), None)

    if ui_index_path:
        @application.get("/", include_in_schema=False)
        async def serve_demo_ui() -> FileResponse:
            return FileResponse(str(ui_index_path), media_type="text/html")

    # -----------------------------------------------------------------------
    # Exception Handlers (Uniform ApiError shape with populated traceId)
    # -----------------------------------------------------------------------
    @application.exception_handler(AccessDeniedError)
    async def access_denied_handler(
        request: Request, exc: AccessDeniedError
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex)
        logging.getLogger(__name__).warning(
            "access_denied path=%s msg=%s trace_id=%s",
            request.url.path,
            exc.message,
            trace_id,
        )
        return _build_api_error(
            status_code=status.HTTP_403_FORBIDDEN,
            error_phrase="Forbidden",
            message=exc.message,
            path=request.url.path,
            trace_id=trace_id,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex)
        errors = exc.errors()
        if errors:
            first_err = errors[0]
            loc = ".".join(str(loc_item) for loc_item in first_err.get("loc", []) if loc_item != "body")
            msg = first_err.get("msg", "request validation failed")
            detail = f"{loc} {msg}".strip() if loc else msg
        else:
            detail = "request validation failed"

        status_code = (
            status.HTTP_400_BAD_REQUEST
            if request.url.path.startswith("/api/v1")
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        error_phrase = (
            "Bad Request"
            if status_code == status.HTTP_400_BAD_REQUEST
            else "Unprocessable Entity"
        )

        logging.getLogger(__name__).info(
            "validation_failed path=%s detail='%s' trace_id=%s status=%s",
            request.url.path,
            detail,
            trace_id,
            status_code,
        )
        return _build_api_error(
            status_code=status_code,
            error_phrase=error_phrase,
            message=detail,
            path=request.url.path,
            trace_id=trace_id,
        )

    @application.exception_handler(DatabaseUnavailableError)
    async def database_unavailable(
        request: Request, exc: DatabaseUnavailableError
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex)
        logging.getLogger(__name__).error(
            "database_unavailable path=%s err=%s trace_id=%s",
            request.url.path,
            str(exc),
            trace_id,
        )
        return _build_api_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_phrase="Service Unavailable",
            message="database service is unavailable",
            path=request.url.path,
            trace_id=trace_id,
        )

    @application.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex)
        try:
            phrase = HTTPStatus(exc.status_code).phrase
        except ValueError:
            phrase = "Error"

        return _build_api_error(
            status_code=exc.status_code,
            error_phrase=phrase,
            message=str(exc.detail),
            path=request.url.path,
            trace_id=trace_id,
        )

    @application.exception_handler(Exception)
    async def unhandled_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex)
        logging.getLogger(__name__).exception(
            "unhandled_exception path=%s trace_id=%s",
            request.url.path,
            trace_id,
        )
        return _build_api_error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_phrase="Internal Server Error",
            message="unexpected server error",
            path=request.url.path,
            trace_id=trace_id,
        )

    return application


app = create_app()
