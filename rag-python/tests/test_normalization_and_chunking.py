"""Tests for canonical normalization and source-aware chunking."""

from app.chunking.source_aware_chunker import SourceAwareChunker
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.normalization.github_normalizer import GitHubNormalizer


def test_github_pr_normalization():
    adapter = GitHubFixtureAdapter()
    normalizer = GitHubNormalizer()

    items, _ = adapter.list_changes()
    pr_item = next(i for i in items if i.metadata.get("kind") == "pull_request")
    acls = adapter.extract_acl(pr_item)

    doc = normalizer.normalize(pr_item, acls)

    assert doc.id == f"doc:{pr_item.id}"
    assert doc.source_type == "GITHUB"
    assert "Pull Request #123" in doc.title
    assert "DC-8692" in doc.metadata["ticket_ids"]
    assert "PaymentValidationService.java" in doc.content
    assert doc.acl_references == acls


def test_github_commit_normalization():
    adapter = GitHubFixtureAdapter()
    normalizer = GitHubNormalizer()

    items, _ = adapter.list_changes()
    commit_item = next(i for i in items if i.metadata.get("kind") == "commit")
    acls = adapter.extract_acl(commit_item)

    doc = normalizer.normalize(commit_item, acls)

    assert doc.id == f"doc:{commit_item.id}"
    assert doc.source_type == "GITHUB"
    assert doc.metadata["kind"] == "commit"
    assert "DC-8692" in doc.metadata["ticket_ids"]
    assert "Touched Files" in doc.content


def test_source_aware_chunking_creates_stable_ids_and_hashes():
    adapter = GitHubFixtureAdapter()
    normalizer = GitHubNormalizer()
    chunker = SourceAwareChunker(target_chunk_chars=400)

    items, _ = adapter.list_changes()
    pr_item = next(i for i in items if i.metadata.get("kind") == "pull_request")
    acls = adapter.extract_acl(pr_item)
    doc = normalizer.normalize(pr_item, acls)

    chunks = chunker.chunk(doc)

    assert len(chunks) >= 1
    for idx, chunk in enumerate(chunks):
        assert chunk.id == f"chunk:{doc.id}:{idx}"
        assert chunk.document_id == doc.id
        assert chunk.chunk_index == idx
        assert len(chunk.content_hash) == 64  # SHA-256
        assert chunk.token_count > 0
        assert chunk.metadata["source_url"] == doc.url
        assert "DC-8692" in chunk.metadata["ticket_ids"]
        # ACLs inherited
        assert len(chunk.acl_references) == len(acls)
        assert chunk.acl_references[0].resource_id == chunk.id
