"""Models for indexing operations, sync checkpoints, and execution metrics."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class SyncStateRecord(BaseModel):
    """Synchronization cursor checkpoint stored in sync_state."""

    source_type: str
    cursor_value: Optional[str] = None
    status: str = "IDLE"  # IDLE, SYNCING, SUCCESS, FAILED
    last_sync_started_at: Optional[datetime] = None
    last_sync_completed_at: Optional[datetime] = None
    records_synced_last_run: int = 0
    error_message: Optional[str] = None


class SyncResult(BaseModel):
    """Result summary returned by the ingestion pipeline."""

    source_type: str
    status: str  # SUCCESS, FAILED
    records_ingested: int = 0
    chunks_indexed: int = 0
    new_cursor: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
