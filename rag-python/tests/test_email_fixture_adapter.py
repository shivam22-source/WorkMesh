"""Tests for EmailFixtureAdapter."""

from pathlib import Path

from app.connectors.common.models import SourceType
from app.connectors.email.fixture_adapter import EmailFixtureAdapter


def test_authenticate_success():
    adapter = EmailFixtureAdapter()
    assert adapter.authenticate() is True
    assert adapter.source_type == SourceType.EMAIL


def test_fetch_item_by_id():
    adapter = EmailFixtureAdapter()
    item_id = "email:alex.engineer@company.internal:msg-101-sent"
    item = adapter.fetch_item(item_id)
    assert item is not None
    assert item.id == item_id
    assert item.source_type == SourceType.EMAIL
    assert item.title == "Validation Flow Refactor for DC-8692"
    assert item.author_id == "alex.engineer@company.internal"
    assert item.metadata["folder"] == "Sent"
    assert len(item.metadata["attachments"]) == 1
    assert item.metadata["attachments"][0]["filename"] == "validation_spec.pdf"
    assert item.metadata["attachments"][0]["size_bytes"] == 1048576


def test_build_source_link_uses_fixture_url():
    adapter = EmailFixtureAdapter()
    item = adapter.fetch_item("email:bob.architect@company.internal:msg-101-inbox")
    assert item is not None
    link = adapter.build_source_link(item)
    assert link == "https://mail.company.internal/mail/bob.architect/inbox/msg-101"
    assert link == item.source_url


def test_list_changes_chronological_sorting():
    adapter = EmailFixtureAdapter()
    items, cursor = adapter.list_changes(cursor=None)
    assert len(items) >= 8
    assert cursor is not None
    assert "#" in cursor

    # Check chronological ordering by updated_at, id
    for i in range(len(items) - 1):
        assert (items[i].updated_at, items[i].id) <= (items[i + 1].updated_at, items[i + 1].id)


def test_list_changes_with_compound_cursor():
    adapter = EmailFixtureAdapter()
    all_items, _ = adapter.list_changes(cursor=None)
    assert len(all_items) >= 8

    # Cut off after second item
    cutoff_item = all_items[1]
    cursor = f"{cutoff_item.updated_at.isoformat()}#{cutoff_item.id}"

    filtered_items, next_cursor = adapter.list_changes(cursor=cursor)
    assert len(filtered_items) == len(all_items) - 2
    assert cutoff_item.id not in [it.id for it in filtered_items]
    assert filtered_items[0].id == all_items[2].id


def test_nonexistent_fixture_path():
    adapter = EmailFixtureAdapter(fixture_path=Path("/tmp/nonexistent_email_data.json"))
    assert adapter.authenticate() is False
    items, cursor = adapter.list_changes(cursor=None)
    assert items == []
    assert cursor is None
    assert adapter.fetch_item("anything") is None
