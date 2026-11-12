"""Wire contract for internal health checks in rag-python.

Every multi-word field carries an explicit camelCase alias so wire payloads remain
consistent across all endpoints.

Contract documentation: docs/api/api-contract.md
"""

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RagHealthRequest(BaseModel):
    """Request body of POST /internal/v1/rag/health."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    requested_by: str = Field(
        validation_alias=AliasChoices("requestedBy", "requested_by"),
        serialization_alias="requestedBy",
        min_length=1,
        description="Calling service or internal client identifier.",
    )
    requested_at: datetime = Field(
        validation_alias=AliasChoices("requestedAt", "requested_at"),
        serialization_alias="requestedAt",
        description="Caller clock at request time. Informational only; the RAG "
        "service uses its own clock for anything that matters.",
    )


class RagHealthResponse(BaseModel):
    """Response body of POST /internal/v1/rag/health."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["ok"] = Field(description="Literal 'ok'; anything else is a failure.")
    service: Literal["rag-python"] = Field(description="Identity of the responding service.")
    contract_version: str = Field(
        validation_alias=AliasChoices("contractVersion", "contract_version"),
        serialization_alias="contractVersion",
        description="Contract version, currently 'v1'.",
    )
    message: str = Field(description="Human-readable detail for logs and demos.")


class ServiceHealth(BaseModel):
    """Body of GET /health and GET /ready. Both fields are single words, so no
    camelCase alias is needed."""

    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
