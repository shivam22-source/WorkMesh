"""Wire contract for internal Grounded RAG ask between backend-java and rag-python.

Contract documentation: docs/api/java-python-contract.md
Java DTOs: com.company.knowledge.search.dto (AskRequest, AskResponse, CitationItem)
"""

from typing import List, Literal, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RagAskRequest(BaseModel):
    """Request payload sent from backend-java to rag-python for permission-aware Q&A."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    question: str = Field(
        min_length=1,
        description="User question string.",
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
    source_types: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("sourceTypes", "source_types"),
        serialization_alias="sourceTypes",
        description="Optional filter by source system (e.g. GITHUB, SLACK, EMAIL).",
    )


class CitationItem(BaseModel):
    """A citation indicating supporting source evidence for an answer claim."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_type: str = Field(
        validation_alias=AliasChoices("sourceType", "source_type"),
        serialization_alias="sourceType",
    )
    title: str
    url: str
    snippet: str


class RagAskResponse(BaseModel):
    """Response payload returned from rag-python to backend-java."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    question: str
    answer: str
    citations: List[CitationItem] = Field(default_factory=list)
    confidence: Literal["LOW", "MEDIUM"]
    status: Literal["ANSWERED", "INSUFFICIENT_EVIDENCE"]
    latency_breakdown_ms: Optional[dict[str, float]] = Field(
        default=None,
        validation_alias=AliasChoices("latencyBreakdownMs", "latency_breakdown_ms"),
        serialization_alias="latencyBreakdownMs",
        description="Timing breakdown in milliseconds across retrieval, reranking, evidence, and LLM.",
    )
