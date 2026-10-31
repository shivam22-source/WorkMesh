"""Data models for knowledge graph entities and relationships (AD-03)."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Canonical entity types for enterprise knowledge graph."""

    TICKET = "TICKET"
    PULL_REQUEST = "PULL_REQUEST"
    COMMIT = "COMMIT"
    SLACK_THREAD = "SLACK_THREAD"
    EMPLOYEE = "EMPLOYEE"


class RelationshipType(str, Enum):
    """Canonical directed relationship types."""

    DISCUSSED_IN = "discussed_in"
    IMPLEMENTED_BY = "implemented_by"
    CONTAINS = "contains"
    AUTHORED_BY = "authored_by"


class Entity(BaseModel):
    """Knowledge graph entity representation adhering to the entities schema."""

    id: str
    entity_type: str
    name: str
    source_record_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Relationship(BaseModel):
    """Canonical directed relationship connecting two entities."""

    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
