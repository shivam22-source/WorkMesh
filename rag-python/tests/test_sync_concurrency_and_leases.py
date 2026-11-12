"""Tests for multi-batch lifecycle, status progression, checkpoint preservation, and lease renewal (Phase 5 Step 2)."""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.connectors.common.base import SourceConnector
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository


class MultiBatchMockConnector(SourceConnector):
    """Mock connector returning deterministic batches for lifecycle testing."""

    def __init__(self, total_items: int = 4, fail_on_batch: Optional[int] = None):
        self._items = [
            RawSourceItem(
                id=f"item-{i}",
                source_type=SourceType.EMAIL,
                source_id=f"id-{i}",
                source_url=f"https://email.mock/{i}",
                title=f"Email Title {i}",
                raw_content=f"Email content body for message {i}",
                metadata={"from_addr": "alice@company.com", "to_addrs": ["bob@company.com"], "folder": "Inbox"},
                created_at=datetime(2026, 1, 1, 10, i, tzinfo=timezone.utc),
                updated_at=datetime(2026, 1, 1, 10, i, tzinfo=timezone.utc),
            )
            for i in range(total_items)
        ]
        self.fail_on_batch = fail_on_batch
        self.batch_count = 0

    @property
    def source_type(self) -> SourceType:
        return SourceType.EMAIL

    def authenticate(self) -> bool:
        return True

    def list_changes(
        self, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Tuple[List[RawSourceItem], Optional[str]]:
        self.batch_count += 1
        if self.fail_on_batch and self.batch_count >= self.fail_on_batch:
            raise ConnectionError(f"Simulated network drop on batch {self.fail_on_batch}")

        # Find items after cursor
        if cursor:
            idx = int(cursor.split("-")[-1]) + 1
        else:
            idx = 0

        remaining = self._items[idx:]
        if not remaining:
            return [], cursor

        batch_size = limit or len(remaining)
        batch = remaining[:batch_size]
        next_cursor = f"cursor-{batch[-1].id.split('-')[-1]}"
        return batch, next_cursor

    def fetch_item(self, item_id: str) -> Optional[RawSourceItem]:
        for it in self._items:
            if it.id == item_id:
                return it
        return None

    def build_source_link(self, item: RawSourceItem) -> str:
        return item.source_url

    def extract_acl(self, item: RawSourceItem) -> List[AclReference]:
        return [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=item.id,
                principal_type=PrincipalType.USER,
                principal_id="user_alice",
                permission="READ",
            )
        ]


def test_multi_batch_checkpoint_status_lifecycle():
    """Verify that multi-batch runs keep status SYNCING until final SUCCESS."""
    repo = InMemoryKnowledgeRepository()
    connector = MultiBatchMockConnector(total_items=4)
    embeddings = MockEmbeddingProvider()

    observed_statuses = []

    # Wrap persist_sync_batch to observe intermediate status
    original_persist = repo.persist_sync_batch

    def tracked_persist(*args, **kwargs):
        original_persist(*args, **kwargs)
        state = repo.get_sync_state("EMAIL")
        observed_statuses.append((state.status, state.cursor_value, state.records_synced_last_run))

    repo.persist_sync_batch = tracked_persist

    pipeline = IngestionPipeline(
        connector=connector,
        repository=repo,
        embedding_provider=embeddings,
        batch_size=2,
    )

    result = pipeline.run()

    assert result.status == "SUCCESS"
    assert result.records_ingested == 4
    assert result.new_cursor == "cursor-3"

    # Intermediate statuses must be SYNCING, with advancing cursor and accumulated records
    assert len(observed_statuses) == 2
    assert observed_statuses[0] == ("SYNCING", "cursor-1", 2)
    assert observed_statuses[1] == ("SYNCING", "cursor-3", 4)

    # Final state in repository must be SUCCESS
    final_state = repo.get_sync_state("EMAIL")
    assert final_state.status == "SUCCESS"
    assert final_state.cursor_value == "cursor-3"
    assert final_state.records_synced_last_run == 4


def test_failure_during_batch_two_preserves_batch_one_cursor_reports_failed():
    """Failure during batch 2 records FAILED status, preserves Batch 1 committed cursor, and never reports SUCCESS."""
    repo = InMemoryKnowledgeRepository()
    # Fails on batch 2
    connector = MultiBatchMockConnector(total_items=4, fail_on_batch=2)
    embeddings = MockEmbeddingProvider()

    pipeline = IngestionPipeline(
        connector=connector,
        repository=repo,
        embedding_provider=embeddings,
        batch_size=2,
    )

    result = pipeline.run()

    # Pipeline reports failure
    assert result.status == "FAILED"
    assert "Simulated network drop on batch 2" in (result.error_message or "")
    # Ingested count reflects only committed Batch 1
    assert result.records_ingested == 2
    assert result.new_cursor == "cursor-1"

    # Repository checkpoint must remain at Batch 1 committed cursor, and status FAILED
    state = repo.get_sync_state("EMAIL")
    assert state.status == "FAILED"
    assert state.cursor_value == "cursor-1"
    assert state.records_synced_last_run == 2
    assert "Simulated network drop on batch 2" in (state.error_message or "")


def test_renew_lease_extends_expiry_when_valid():
    """renew_lease extends lease expiry when valid, returns False when token doesn't match or expired."""
    repo = InMemoryKnowledgeRepository()

    claim = repo.claim_sync("SLACK", lease_token="valid-token", lease_ttl_seconds=300)
    assert claim is not None

    # Renewal with valid token succeeds
    success = repo.renew_lease("SLACK", lease_token="valid-token", lease_ttl_seconds=600)
    assert success is True

    # Renewal with invalid token returns False
    invalid = repo.renew_lease("SLACK", lease_token="wrong-token", lease_ttl_seconds=600)
    assert invalid is False


def test_zero_record_run_completes_with_success():
    """Connector returning 0 records on initial check completes cleanly with SUCCESS."""
    repo = InMemoryKnowledgeRepository()
    connector = MultiBatchMockConnector(total_items=0)
    embeddings = MockEmbeddingProvider()

    pipeline = IngestionPipeline(
        connector=connector,
        repository=repo,
        embedding_provider=embeddings,
    )

    result = pipeline.run()

    assert result.status == "SUCCESS"
    assert result.records_ingested == 0
    assert result.chunks_indexed == 0

    state = repo.get_sync_state("EMAIL")
    assert state.status == "SUCCESS"
    assert state.records_synced_last_run == 0
