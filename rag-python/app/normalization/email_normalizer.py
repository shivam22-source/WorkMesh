"""Normalizer converting raw email messages into canonical documents."""

from typing import List

from app.connectors.common.models import AclReference, RawSourceItem
from app.normalization.common import extract_ticket_ids
from app.normalization.models import CanonicalDocument


class EmailNormalizer:
    """Converts raw email source items into CanonicalDocuments with strict privacy and metadata references."""

    def normalize(
        self, raw_item: RawSourceItem, acl_references: List[AclReference]
    ) -> CanonicalDocument:
        meta = raw_item.metadata
        mailbox = meta.get("mailbox", "")
        folder = meta.get("folder", "INBOX")
        message_id = meta.get("message_id", raw_item.source_id)
        thread_id = meta.get("thread_id", "")
        from_addr = meta.get("from_addr", raw_item.author_id or "unknown")
        to_addrs = meta.get("to_addrs", [])
        cc_addrs = meta.get("cc_addrs", [])
        attachments = meta.get("attachments", [])

        # Extract referenced ticket IDs
        combined_text = f"{raw_item.title or ''}\n{raw_item.raw_content}"
        detected_tickets = extract_ticket_ids(combined_text)
        all_tickets = sorted(list(set(detected_tickets)))

        # Format date string in UTC
        date_str = raw_item.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Build clean structured Markdown representing the email
        sections = [
            f"# Email: {raw_item.title or 'No Subject'}",
            f"**Message-ID:** `{message_id}` | **Thread-ID:** `{thread_id}`",
            f"**From:** `{from_addr}`",
            f"**To:** {', '.join(f'`{t}`' for t in to_addrs) if to_addrs else 'None'}",
        ]

        if cc_addrs:
            sections.append(f"**Cc:** {', '.join(f'`{c}`' for c in cc_addrs)}")

        sections.extend([
            f"**Date:** `{date_str}`",
            f"**Folder:** `{folder}` | **Mailbox:** `{mailbox}`",
            f"**Source Link:** {raw_item.source_url}",
        ])

        if all_tickets:
            sections.append(f"**Referenced Tickets:** {', '.join(all_tickets)}")

        # Body section
        sections.append(f"## Message Body\n\n{raw_item.raw_content.strip()}")

        # Attachments section (metadata references only; no binary ingestion)
        if attachments:
            att_lines = []
            for a in attachments:
                fname = a.get("filename", "attachment")
                mime = a.get("mime_type", "application/octet-stream")
                size = a.get("size_bytes", 0)
                att_lines.append(f"- [Attachment: {fname} ({mime}, {size} bytes)]")
            sections.append(f"## Attachments ({len(attachments)})\n\n" + "\n".join(att_lines))

        canonical_content = "\n\n".join(sections)
        doc_id = f"doc:{raw_item.id}"
        formatted_title = f"Email: {raw_item.title or 'No Subject'}"

        # Note: BCC is strictly excluded from doc_meta and canonical_content
        doc_meta = {
            "mailbox": mailbox,
            "folder": folder,
            "message_id": message_id,
            "thread_id": thread_id,
            "from_addr": from_addr,
            "to_addrs": to_addrs,
            "cc_addrs": cc_addrs,
            "ticket_ids": all_tickets,
            "attachments": [
                {
                    "filename": a.get("filename"),
                    "mime_type": a.get("mime_type"),
                    "size_bytes": a.get("size_bytes"),
                }
                for a in attachments
            ],
        }

        return CanonicalDocument(
            id=doc_id,
            source_record_id=raw_item.id,
            source_type=raw_item.source_type.value,
            title=formatted_title,
            content=canonical_content,
            author=from_addr,
            url=raw_item.source_url,
            metadata=doc_meta,
            acl_references=acl_references,
            created_at=raw_item.created_at,
            updated_at=raw_item.updated_at,
        )
