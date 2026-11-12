"""Canonical document model (AD-07, AD-08).

Normalizes divergent source objects (GitHub PR, commit, Slack thread, email)
into a unified representation for chunking, indexing, and permission assignment.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.connectors.common.models import AclReference


class CanonicalDocument(BaseModel):
    """Source-independent canonical document representation."""

    id: str  # Deterministic ID e.g. "doc:github:company/payment-service:pr:123"
    source_record_id: str
    source_type: str
    title: str
    content: str
    author: Optional[str] = None
    url: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    acl_references: List[AclReference] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
