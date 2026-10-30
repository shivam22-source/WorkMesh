"""Normalizer converting raw Slack thread items into canonical documents."""

from datetime import datetime, timezone
from typing import List

from app.connectors.common.models import AclReference, RawSourceItem
from app.normalization.common import extract_ticket_ids
from app.normalization.models import CanonicalDocument


def _format_slack_time(ts_val: str) -> str:
    try:
        dt = datetime.fromtimestamp(float(ts_val), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError):
        return ts_val


class SlackNormalizer:
    """Converts raw Slack threads into structured CanonicalDocuments."""

    def normalize(
        self, raw_item: RawSourceItem, acl_references: List[AclReference]
    ) -> CanonicalDocument:
        meta = raw_item.metadata
        channel_name = meta.get("channel_name", "general")
        channel_id = meta.get("channel_id", "")
        thread_ts = meta.get("thread_ts", raw_item.source_id)
        parent_msg = meta.get("parent_message", {})
        replies = meta.get("replies", [])
        workspace = meta.get("workspace", "company.slack.com")

        # Extract ticket IDs from full raw content and metadata
        combined_text = f"{raw_item.title or ''}\n{raw_item.raw_content}"
        detected_tickets = extract_ticket_ids(combined_text)
        all_tickets = sorted(list(set(meta.get("ticket_ids", []) + detected_tickets)))

        parent_author = parent_msg.get("user", raw_item.author_id or "unknown")
        parent_time = _format_slack_time(parent_msg.get("ts", thread_ts))
        parent_text = parent_msg.get("text", raw_item.raw_content).strip()

        # Build clean structured Markdown representing the thread
        sections = [
            f"# Slack Conversation in #{channel_name}",
            f"**Channel:** `#{channel_name}` (`{channel_id}`) | **Workspace:** `{workspace}`",
            f"**Thread Link:** {raw_item.source_url}",
        ]

        if all_tickets:
            sections.append(f"**Referenced Tickets:** {', '.join(all_tickets)}")

        dialogue_sections = [
            f"**{parent_author}** ({parent_time}):\n{parent_text}"
        ]

        for r in replies:
            r_author = r.get("user", "unknown")
            r_time = _format_slack_time(r.get("ts", ""))
            r_text = r.get("text", "").strip()
            dialogue_sections.append(f"**{r_author}** ({r_time}):\n{r_text}")

        sections.append("## Thread Discussion\n\n" + "\n\n".join(dialogue_sections))

        canonical_content = "\n\n".join(sections)
        doc_id = f"doc:{raw_item.id}"
        formatted_title = f"#{channel_name}: {raw_item.title or 'Slack Thread'}"

        doc_meta = {
            "workspace": workspace,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "thread_ts": thread_ts,
            "reply_count": len(replies),
            "ticket_ids": all_tickets,
            "author": parent_author,
        }

        return CanonicalDocument(
            id=doc_id,
            source_record_id=raw_item.id,
            source_type=raw_item.source_type.value,
            title=formatted_title,
            content=canonical_content,
            author=parent_author,
            url=raw_item.source_url,
            metadata=doc_meta,
            acl_references=acl_references,
            created_at=raw_item.created_at,
            updated_at=raw_item.updated_at,
        )
