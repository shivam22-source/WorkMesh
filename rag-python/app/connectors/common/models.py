"""Common domain models for source ingestion and access control."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    GITHUB = "GITHUB"
    SLACK = "SLACK"
    EMAIL = "EMAIL"
    JIRA = "JIRA"


class PrincipalType(str, Enum):
    USER = "USER"
    GROUP = "GROUP"
    ROLE = "ROLE"
    PUBLIC = "PUBLIC"


class AclReference(BaseModel):
    """Access control reference indicating who may view a resource."""

    resource_type: str = "SOURCE_RECORD"  # SOURCE_RECORD, DOCUMENT, CHUNK
    resource_id: str
    principal_type: PrincipalType = PrincipalType.GROUP
    principal_id: str
    permission: str = "READ"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RawSourceItem(BaseModel):
    """Raw item extracted from a source system before normalization."""

    id: str  # Unique external identifier: e.g. "github:company/repo:pr:123"
    source_type: SourceType
    source_id: str  # Native ID in the source system (e.g. "123", commit SHA)
    source_url: str  # Permanent URL to source
    title: Optional[str] = None
    author_id: Optional[str] = None
    raw_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime
    updated_at: datetime
