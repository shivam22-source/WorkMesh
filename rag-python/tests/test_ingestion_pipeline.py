"""Tests for end-to-end ingestion pipeline and checkpoint handling."""

from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository


def test_pipeline_runs_and_populates_repository():
    connector = GitHubFixtureAdapter()
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    pipeline = IngestionPipeline(
        connector=connector,
        repository=repo,
        embedding_provider=embeddings,
    )

    result = pipeline.run()

    assert result.status == "SUCCESS"
    assert result.records_ingested == 3
    assert result.chunks_indexed >= 3
    assert result.new_cursor is not None

    # Check repository state
    assert len(repo.source_records) == 3
    assert len(repo.documents) == 3
    assert len(repo.chunks) == result.chunks_indexed
    assert len(repo.acls) > 0

    # Ensure all chunks have embeddings
    for chunk in repo.chunks.values():
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 384

    # Verify sync checkpoint
    sync_state = repo.get_sync_state("GITHUB")
    assert sync_state is not None
    assert sync_state.status == "SUCCESS"
    assert sync_state.cursor_value == result.new_cursor
    assert sync_state.records_synced_last_run == 3


def test_pipeline_incremental_sync_does_not_duplicate():
    connector = GitHubFixtureAdapter()
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    pipeline = IngestionPipeline(
        connector=connector,
        repository=repo,
        embedding_provider=embeddings,
    )

    # First run
    result1 = pipeline.run()
    assert result1.records_ingested == 3

    # Second run immediately after
    result2 = pipeline.run()
    assert result2.status == "SUCCESS"
    assert result2.records_ingested == 0
    assert result2.chunks_indexed == 0
    assert result2.new_cursor == result1.new_cursor
