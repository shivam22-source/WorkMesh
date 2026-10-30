"""FastAPI application factory for rag-python.

The factory exists so tests can build an isolated app instance instead of
importing a module-level singleton.
"""

from datetime import datetime, timezone
import logging
import sys

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import health, internal_rag
from app.common.config import get_settings


def configure_logging(level: str) -> None:
    """Emit one JSON object per log line so Phase 6 does not have to retrofit it."""
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


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="rag-python",
        version="0.0.1",
        description=(
            "RAG and ingestion service. Phase 1 exposes health endpoints, "
            "and service-contract stubs for health and search."
        ),
    )
    application.include_router(health.router)
    application.include_router(internal_rag.router)

    @application.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Return the same error shape backend-java uses.

        The message is deliberately generic; the detail stays in the log so an
        internal error cannot leak internals to a caller.
        """
        logging.getLogger(__name__).exception(
            "unhandled_exception path=%s", request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error": "Internal Server Error",
                "message": "unexpected server error",
                "path": request.url.path,
                "traceId": None,
            },
        )

    return application


app = create_app()
