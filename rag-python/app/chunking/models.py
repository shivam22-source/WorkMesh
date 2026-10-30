"""Models for knowledge chunks (the unit of search, retrieval, and ACL filtering)."""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.connectors.common.models import AclReference


class CanonicalChunk(BaseModel):
    """A searchable unit derived from a canonical document."""

    id: str  # Deterministic stable ID: e.g. "chunk:doc:...:0"
    document_id: str
    chunk_index: int
    content: str
    token_count: int
    content_hash: str  # SHA-256 hash for deduplication and change tracking
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    acl_references: List[AclReference] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def compute_hash(cls, text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
