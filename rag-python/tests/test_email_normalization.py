"""Tests for EmailNormalizer."""

from app.connectors.email.fixture_adapter import EmailFixtureAdapter
from app.normalization.email_normalizer import EmailNormalizer


def test_normalize_email_to_canonical_document():
    adapter = EmailFixtureAdapter()
    normalizer = EmailNormalizer()

    raw_item = adapter.fetch_item("email:bob.architect@company.internal:msg-101-inbox")
    assert raw_item is not None
    acls = adapter.extract_acl(raw_item)

    doc = normalizer.normalize(raw_item, acls)

    assert doc.id == "doc:email:bob.architect@company.internal:msg-101-inbox"
    assert doc.source_record_id == raw_item.id
    assert doc.source_type == "EMAIL"
    assert doc.title == "Email: Validation Flow Refactor for DC-8692"
    assert doc.author == "alex.engineer@company.internal"
    assert doc.url == "https://mail.company.internal/mail/bob.architect/inbox/msg-101"

    # Verify structured content sections
    assert "# Email: Validation Flow Refactor for DC-8692" in doc.content
    assert "**Message-ID:** `<msg-101@company.internal>`" in doc.content
    assert "**From:** `alex.engineer@company.internal`" in doc.content
    assert "**To:** `bob.architect@company.internal`" in doc.content
    assert "**Folder:** `INBOX` | **Mailbox:** `bob.architect@company.internal`" in doc.content
    assert "**Source Link:** https://mail.company.internal/mail/bob.architect/inbox/msg-101" in doc.content
    assert "## Message Body" in doc.content
    assert "strict fail-closed validation on startup" in doc.content


def test_ticket_reference_extraction():
    adapter = EmailFixtureAdapter()
    normalizer = EmailNormalizer()

    raw_item = adapter.fetch_item("email:bob.architect@company.internal:msg-101-inbox")
    assert raw_item is not None
    acls = adapter.extract_acl(raw_item)

    doc = normalizer.normalize(raw_item, acls)
    assert "DC-8692" in doc.metadata["ticket_ids"]
    assert "**Referenced Tickets:** DC-8692" in doc.content


def test_attachment_metadata_only_no_hash_no_binary():
    adapter = EmailFixtureAdapter()
    normalizer = EmailNormalizer()

    raw_item = adapter.fetch_item("email:alex.engineer@company.internal:msg-101-sent")
    assert raw_item is not None
    acls = adapter.extract_acl(raw_item)

    doc = normalizer.normalize(raw_item, acls)

    # Attachments in metadata
    attachments = doc.metadata.get("attachments", [])
    assert len(attachments) == 1
    att = attachments[0]
    assert att["filename"] == "validation_spec.pdf"
    assert att["mime_type"] == "application/pdf"
    assert att["size_bytes"] == 1048576

    # Verify no invented hash and no download URL
    assert "sha256" not in att
    assert "download_url" not in att

    # Text rendering in content
    assert "## Attachments (1)" in doc.content
    assert "[Attachment: validation_spec.pdf (application/pdf, 1048576 bytes)]" in doc.content


def test_bcc_privacy_in_content():
    adapter = EmailFixtureAdapter()
    normalizer = EmailNormalizer()

    # Bob's copy: Dave's address must not exist in content, title, or metadata
    bob_item = adapter.fetch_item("email:bob.architect@company.internal:msg-201-inbox")
    assert bob_item is not None
    bob_doc = normalizer.normalize(bob_item, adapter.extract_acl(bob_item))

    assert "dave.intern" not in bob_doc.content
    assert "dave.intern" not in bob_doc.title
    assert "dave.intern" not in str(bob_doc.metadata)

    # Dave's BCC copy: content must not have a public 'Bcc:' line
    dave_item = adapter.fetch_item("email:dave.intern@company.internal:msg-201-inbox")
    assert dave_item is not None
    dave_doc = normalizer.normalize(dave_item, adapter.extract_acl(dave_item))

    assert "**Bcc:**" not in dave_doc.content
