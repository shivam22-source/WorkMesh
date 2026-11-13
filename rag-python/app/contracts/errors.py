"""Shared API error response models."""

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Structured error detail payload returned on all API errors."""

    code: str = Field(..., description="Stable machine-readable error code.")
    message: str = Field(..., description="Human-readable error description.")
    request_id: str = Field(..., description="Request correlation identifier matching X-Request-Id.")


class ErrorResponse(BaseModel):
    """Uniform error envelope returned across all endpoints."""

    error: ErrorDetail
