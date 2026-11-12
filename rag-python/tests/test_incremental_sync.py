"""Tests for compound cursor pagination, incremental sync, and strict UTC ISO parsing (Phase 5 Step 2)."""

from datetime import datetime, timezone

import pytest

from app.connectors.common.base import SourceConnector
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.connectors.email.fixture_adapter import parse_strict_utc_iso
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository


def test_strict_utc_iso_parsing_valid_and_invalid():
    """Verify that parse_strict_utc_iso normalizes timezone-aware timestamps to UTC and rejects naive/malformed strings."""
    # 1. Valid UTC Z
    dt_z = parse_strict_utc_iso("2026-05-10T14:30:00Z")
    assert dt_z.tzinfo == timezone.utc
    assert dt_z.hour == 14
    assert dt_z.minute == 30

    # 2. Valid explicit offset +02:00 normalized to UTC
    dt_offset = parse_strict_utc_iso("2026-05-10T16:30:00+02:00")
    assert dt_offset.tzinfo == timezone.utc
    assert dt_offset.hour == 14  # 16:30 +02:00 == 14:30 UTC

    # 3. Timezone-naive ISO rejected
    with pytest.raises(ValueError, match="Naive timestamp rejected"):
        parse_strict_utc_iso("2026-05-10T14:30:00")

    # 4. Malformed strings rejected
    with pytest.raises(ValueError, match="Malformed ISO-8601"):
        parse_strict_utc_iso("invalid-timestamp")

    with pytest.raises(ValueError, match="non-empty string"):
        parse_strict_utc_iso("")


class CompoundCursorMockConnector(SourceConnector):
    """Mock connector returning records with compound timestamps and stable IDs."""

    def __init__(self, items):
        self._items = items

    @property
    def source_type(self) -> SourceType:
        return SourceType.EMAIL

    def authenticate(self) -> bool:
        return True

    def list_changes(self, cursor=None, limit=None):
        if not self._items:
            return [], cursor

        if cursor and "#" in cursor:
            ts_str, id_str = cursor.split("#", 1)
            cursor_dt = parse_strict_utc_iso(ts_str)
            filtered = [
                it for it in self._items
                if (it.updated_at > cursor_dt) or (it.updated_at == cursor_dt and it.id > id_str)
            ]
        else:
            filtered = self._items

        if not filtered:
            return [], cursor

        batch = filtered[:limit] if limit and limit > 0 else filtered
        last = batch[-1]
        next_c = f"{last.updated_at.astimezone(timezone.utc).isoformat()}#{last.id}"
        return batch, next_c

    def fetch_item(self, item_id: str):
        return None

    def build_source_link(self, item: RawSourceItem):
        return item.source_url

    def extract_acl(self, item: RawSourceItem):
        return [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=item.id,
                principal_type=PrincipalType.PUBLIC,
                principal_id="*",
                permission="READ",
            )
        ]


def test_compound_cursor_pagination_and_sorting():
    """Verify that multiple items with identical timestamps paginate deterministically using compound cursor."""
    shared_ts = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    items = [
        RawSourceItem(
            id=f"item-A-{i}", source_type=SourceType.EMAIL, source_id=f"A-{i}",
            source_url=f"https://msg/A-{i}", title=f"Title A-{i}", raw_content="Body",
            created_at=shared_ts, updated_at=shared_ts,
        )
        for i in range(5)
    ]

    connector = CompoundCursorMockConnector(items)

    # Page 1: limit 2
    batch1, cursor1 = connector.list_changes(cursor=None, limit=2)
    assert len(batch1) == 2
    assert [it.id for it in batch1] == ["item-A-0", "item-A-1"]
    assert cursor1.endswith("#item-A-1")

    # Page 2: limit 2
    batch2, cursor2 = connector.list_changes(cursor=cursor1, limit=2)
    assert len(batch2) == 2
    assert [it.id for it in batch2] == ["item-A-2", "item-A-3"]
    assert cursor2.endswith("#item-A-3")

    # Page 3: limit 2 (last item)
    batch3, cursor3 = connector.list_changes(cursor=cursor2, limit=2)
    assert len(batch3) == 1
    assert [it.id for it in batch3] == ["item-A-4"]
    assert cursor3.endswith("#item-A-4")

    # Page 4: empty
    batch4, cursor4 = connector.list_changes(cursor=cursor3, limit=2)
    assert len(batch4) == 0
    assert cursor4 == cursor3


def test_incremental_sync_across_multiple_runs():
    """Verify that successive pipeline runs only ingest changed records and advance checkpoint."""
    ts1 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)

    all_items = [
        RawSourceItem(
            id="item-1", source_type=SourceType.EMAIL, source_id="1",
            source_url="https://msg/1", title="Title 1", raw_content="Body 1",
            created_at=ts1, updated_at=ts1,
        ),
        RawSourceItem(
            id="item-2", source_type=SourceType.EMAIL, source_id="2",
            source_url="https://msg/2", title="Title 2", raw_content="Body 2",
            created_at=ts1, updated_at=ts1,
        ),
    ]

    # Run 1: Connector has 2 items
    connector = CompoundCursorMockConnector(all_items)
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    pipeline = IngestionPipeline(connector=connector, repository=repo, embedding_provider=embeddings)
    res1 = pipeline.run()
    assert res1.status == "SUCCESS"
    assert res1.records_ingested == 2

    # Run 2: No new items
    res2 = pipeline.run()
    assert res2.status == "SUCCESS"
    assert res2.records_ingested == 0
    assert res2.new_cursor == res1.new_cursor

    # Run 3: Item 3 added
    item3 = RawSourceItem(
        id="item-3", source_type=SourceType.EMAIL, source_id="3",
        source_url="https://msg/3", title="Title 3", raw_content="Body 3",
        created_at=ts2, updated_at=ts2,
    )
    all_items.append(item3)
    connector._items = all_items

    res3 = pipeline.run()
    assert res3.status == "SUCCESS"
    assert res3.records_ingested == 1
    assert res3.new_cursor.endswith("#item-3")
