"""Tests for GitHubFixtureAdapter and synthetic fixture parsing."""

from app.connectors.github.fixture_adapter import GitHubFixtureAdapter


def test_fixture_adapter_loads_prs_and_commits():
    adapter = GitHubFixtureAdapter()
    assert adapter.authenticate() is True

    items, cursor = adapter.list_changes(cursor=None)
    assert len(items) == 3  # 1 PR + 2 Commits

    # Verify PR
    prs = [i for i in items if i.metadata.get("kind") == "pull_request"]
    assert len(prs) == 1
    pr = prs[0]
    assert pr.source_id == "123"
    assert "DC-8692" in pr.title
    assert pr.author_id == "alex-engineer"
    assert "DC-8692" in pr.metadata.get("ticket_ids", [])
    assert len(pr.metadata.get("changed_files", [])) == 2

    # Verify Commits
    commits = [i for i in items if i.metadata.get("kind") == "commit"]
    assert len(commits) == 2
    commit_shas = {c.source_id for c in commits}
    assert "8af2d1e94b2a8d3e" in commit_shas
    assert "b4c90e1f7a3d2c11" in commit_shas

    for c in commits:
        assert c.author_id == "alex-engineer"
        assert "DC-8692" in c.metadata.get("ticket_ids", [])


def test_fixture_adapter_extracts_acls():
    adapter = GitHubFixtureAdapter()
    items, _ = adapter.list_changes()
    assert items

    acls = adapter.extract_acl(items[0])
    principal_ids = {a.principal_id for a in acls}
    assert "group_engineering" in principal_ids
    assert "group_backend" in principal_ids


def test_fixture_adapter_incremental_cursor():
    adapter = GitHubFixtureAdapter()
    items, cursor = adapter.list_changes(cursor=None)
    assert len(items) == 3
    assert cursor is not None

    # Listing changes with the latest cursor should yield 0 new items
    subsequent_items, new_cursor = adapter.list_changes(cursor=cursor)
    assert len(subsequent_items) == 0
    assert new_cursor == cursor
