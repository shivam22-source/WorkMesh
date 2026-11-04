"""Wire contract between backend-java and rag-python.

This module is the Python side of the contract. The Java side is
`com.company.knowledge.orchestrator.ragclient.dto`:

    RagHealthRequest  <-> RagHealthRequest
    RagHealthResponse <-> RagHealthResponse

Naming note: Java records serialise to camelCase by default, while Pydantic
defaults to snake_case. Every multi-word field therefore carries an explicit
alias. Without this, Java sends `requestedBy` and Pydantic rejects the body
with 422 — which is exactly what the contract test caught during Phase 0.

Both sides serialise by alias, so the wire format is camelCase everywhere.

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
        description="Calling service name. Only 'backend-java' is valid today.",
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