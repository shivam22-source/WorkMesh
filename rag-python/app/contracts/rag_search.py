"""Wire contract for internal search between backend-java and rag-python.

This module defines the Python side of the search contract stub for Phase 1.
Java side: com.company.knowledge.orchestrator.ragclient.dto (RagSearchRequest, RagSearchResponse, RagSearchResultItem).

Contract documentation: docs/api/java-python-contract.md
"""

from typing import List, Literal, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RagSearchRequest(BaseModel):
    """Request payload sent from backend-java to rag-python for permission-filtered search."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query: str = Field(
        min_length=1,
        description="Search query string or keywords.",
    )
    user_id: str = Field(
        validation_alias=AliasChoices("userId", "user_id"),
        serialization_alias="userId",
        min_length=1,
        description="Authenticated employee identity resolved by backend-java.",
    )
    group_ids: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("groupIds", "group_ids"),
        serialization_alias="groupIds",
        description="Team/group memberships resolved by backend-java.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of candidates to retrieve.",
    )
    source_types: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("sourceTypes", "source_types"),
        serialization_alias="sourceTypes",
        description="Optional filter by source system (e.g. GITHUB, SLACK, EMAIL).",
    )


class RagSearchResultItem(BaseModel):
    """A single candidate search item returned by rag-python."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    chunk_id: str = Field(
        validation_alias=AliasChoices("chunkId", "chunk_id"),
        serialization_alias="chunkId",
    )
    document_id: str = Field(
        validation_alias=AliasChoices("documentId", "document_id"),
        serialization_alias="documentId",
    )
    source_type: str = Field(
        validation_alias=AliasChoices("sourceType", "source_type"),
        serialization_alias="sourceType",
    )
    title: str
    snippet: str
    source_url: str = Field(
        validation_alias=AliasChoices("sourceUrl", "source_url"),
        serialization_alias="sourceUrl",
    )
    author: Optional[str] = None
    score: float


class RagSearchResponse(BaseModel):
    """Response payload returned from rag-python to backend-java."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["ok"] = Field(description="Literal 'ok'; anything else is an error.")
    query: str
    total_results: int = Field(
        validation_alias=AliasChoices("totalResults", "total_results"),
        serialization_alias="totalResults",
    )
    results: List[RagSearchResultItem] = Field(default_factory=list)
