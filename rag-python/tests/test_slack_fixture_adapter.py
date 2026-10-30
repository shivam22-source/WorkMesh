"""Tests for Slack fixture ingestion, normalization, and pipeline integration."""

from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository
from app.normalization.slack_normalizer import SlackNormalizer


def test_slack_fixture_loads_threads_and_messages():
    adapter = SlackFixtureAdapter()
    assert adapter.authenticate() is True

    items, cursor = adapter.list_changes(cursor=None)
    assert len(items) == 2  # Two threads in synthetic fixture
    assert cursor is not None

    # Check thread discussing DC-8692 in #payments-engineering
    payments_thread = next(i for i in items if i.metadata.get("channel_name") == "payments-engineering")
    assert payments_thread.source_id == "1697364000.000100"
    assert payments_thread.author_id == "alex-engineer"
    assert "DC-8692" in payments_thread.metadata.get("ticket_ids", [])
    assert payments_thread.metadata.get("reply_count") == 2
    assert "C0123PAY" in payments_thread.id

    # Check that replies are preserved in metadata
    replies = payments_thread.metadata.get("replies", [])
    assert len(replies) == 2
    assert replies[0]["user"] == "sam-reviewer"
    assert "PR #123" in replies[1]["text"]


def test_slack_fixture_extracts_acls():
    adapter = SlackFixtureAdapter()
    items, _ = adapter.list_changes()
    assert items

    acls = adapter.extract_acl(items[0])
    principal_ids = {a.principal_id for a in acls}
    assert "group_engineering" in principal_ids
    assert "group_backend" in principal_ids


def test_slack_fixture_incremental_cursor():
    adapter = SlackFixtureAdapter()
    items, cursor = adapter.list_changes(cursor=None)
    assert len(items) == 2
    assert cursor is not None

    # Listing changes with the latest cursor returns 0 items
    subsequent_items, new_cursor = adapter.list_changes(cursor=cursor)
    assert len(subsequent_items) == 0
    assert new_cursor == cursor


def test_slack_normalizer_creates_canonical_document():
    adapter = SlackFixtureAdapter()
    normalizer = SlackNormalizer()

    items, _ = adapter.list_changes()
    payments_thread = next(i for i in items if i.metadata.get("channel_name") == "payments-engineering")
    acls = adapter.extract_acl(payments_thread)

    doc = normalizer.normalize(payments_thread, acls)

    assert doc.id == f"doc:{payments_thread.id}"
    assert doc.source_type == "SLACK"
    assert "payments-engineering" in doc.title
    assert doc.author == "alex-engineer"
    assert "DC-8692" in doc.metadata["ticket_ids"]
    assert doc.metadata["reply_count"] == 2

    # Verify structured Markdown content
    assert "# Slack Conversation in #payments-engineering" in doc.content
    assert "**Thread Link:**" in doc.content
    assert "**Referenced Tickets:** DC-8692" in doc.content
    assert "**alex-engineer**" in doc.content
    assert "**sam-reviewer**" in doc.content
    assert "HTTP 400 Bad Request" in doc.content
    assert doc.acl_references == acls


def test_slack_ingestion_pipeline_end_to_end():
    connector = SlackFixtureAdapter()
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    pipeline = IngestionPipeline(
        connector=connector,
        repository=repo,
        embedding_provider=embeddings,
    )

    result = pipeline.run()

    assert result.status == "SUCCESS"
    assert result.source_type == "SLACK"
    assert result.records_ingested == 2
    assert result.chunks_indexed >= 2
    assert result.new_cursor is not None

    # Check repository state
    assert len(repo.source_records) == 2
    assert len(repo.documents) == 2
    assert len(repo.chunks) == result.chunks_indexed
    assert len(repo.acls) > 0

    # Ensure all Slack chunks have embeddings and metadata
    for chunk in repo.chunks.values():
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 1536
        assert chunk.metadata["source_type"] == "SLACK"
        assert "payments-engineering" in chunk.metadata.get("title", "") or "general-dev" in chunk.metadata.get("title", "")

    # Verify sync checkpoint
    sync_state = repo.get_sync_state("SLACK")
    assert sync_state is not None
    assert sync_state.status == "SUCCESS"
    assert sync_state.cursor_value == result.new_cursor
    assert sync_state.records_synced_last_run == 2
