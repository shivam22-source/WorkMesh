"""Slack fixture connector for deterministic local development and evaluation (AD-08).

Reads synthetic Slack channels and thread conversations without network calls.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.connectors.common.base import SourceConnector
from app.connectors.common.models import (
    AclReference,
    PrincipalType,
    RawSourceItem,
    SourceType,
)

logger = logging.getLogger(__name__)


def _slack_ts_to_datetime(ts_str: str) -> datetime:
    """Convert Slack timestamp (e.g. '1697364000.000100') to UTC datetime."""
    try:
        epoch = float(ts_str)
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


class SlackFixtureAdapter(SourceConnector):
    """Deterministic fixture adapter reading synthetic Slack threads from JSON."""

    def __init__(self, fixture_path: Optional[Path] = None):
        if fixture_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
            self.fixture_path = base_dir / "data" / "fixtures" / "slack" / "sample_slack_data.json"
        else:
            self.fixture_path = Path(fixture_path)

        self._items: List[RawSourceItem] = []
        self._loaded = False

    @property
    def source_type(self) -> SourceType:
        return SourceType.SLACK

    def authenticate(self) -> bool:
        """Fixture adapter is always authenticated if the fixture file exists."""
        return self.fixture_path.exists()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        if not self.fixture_path.exists():
            logger.warning("slack_fixture_file_not_found path=%s", self.fixture_path)
            self._items = []
            self._loaded = True
            return

        with open(self.fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        workspace = data.get("workspace", "company.slack.com")
        items: List[RawSourceItem] = []

        for channel in data.get("channels", []):
            channel_id = channel.get("id", "C000000")
            channel_name = channel.get("name", "general")
            is_private = channel.get("is_private", False)

            for thread in channel.get("threads", []):
                thread_ts = thread.get("thread_ts")
                parent = thread.get("parent_message", {})
                replies = thread.get("replies", [])
                ticket_ids = thread.get("ticket_ids", [])
                permalink = thread.get("permalink") or f"https://{workspace}/archives/{channel_id}/p{thread_ts.replace('.', '')}"

                parent_text = parent.get("text", "")
                parent_author = parent.get("user", "unknown")
                created_at = _slack_ts_to_datetime(parent.get("ts", thread_ts))

                # Determine updated_at from the latest reply or parent message
                if replies:
                    updated_at = _slack_ts_to_datetime(replies[-1].get("ts", thread_ts))
                else:
                    updated_at = created_at

                # Build serialized raw text combining parent and replies
                dialogue_lines = [f"{parent_author}: {parent_text}"]
                for r in replies:
                    dialogue_lines.append(f"{r.get('user', 'unknown')}: {r.get('text', '')}")
                raw_content = "\n".join(dialogue_lines)

                # Generate title
                snippet = parent_text.splitlines()[0] if parent_text else "Conversation"
                if len(snippet) > 60:
                    snippet = snippet[:57] + "..."
                title = f"#{channel_name}: {snippet}"

                item_id = f"slack:{channel_id}:thread:{thread_ts}"

                raw_item = RawSourceItem(
                    id=item_id,
                    source_type=SourceType.SLACK,
                    source_id=thread_ts,
                    source_url=permalink,
                    title=title,
                    author_id=parent_author,
                    raw_content=raw_content,
                    metadata={
                        "workspace": workspace,
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "is_private": is_private,
                        "thread_ts": thread_ts,
                        "parent_message": parent,
                        "replies": replies,
                        "reply_count": len(replies),
                        "ticket_ids": ticket_ids,
                    },
                    created_at=created_at,
                    updated_at=updated_at,
                )
                items.append(raw_item)

        items.sort(key=lambda x: x.updated_at)
        self._items = items
        self._loaded = True
        logger.info("loaded_slack_fixtures count=%d from=%s", len(items), self.fixture_path)

    def list_changes(
        self, cursor: Optional[str] = None
    ) -> Tuple[List[RawSourceItem], Optional[str]]:
        self._ensure_loaded()
        if not self._items:
            return [], cursor

        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
                filtered = [item for item in self._items if item.updated_at > cursor_dt]
            except ValueError:
                filtered = self._items
        else:
            filtered = self._items

        if not filtered:
            return [], cursor

        next_cursor = filtered[-1].updated_at.isoformat()
        return filtered, next_cursor

    def fetch_item(self, item_id: str) -> Optional[RawSourceItem]:
        self._ensure_loaded()
        for item in self._items:
            if item.id == item_id or item.source_id == item_id:
                return item
        return None

    def build_source_link(self, item: RawSourceItem) -> str:
        return item.source_url

    def extract_acl(self, item: RawSourceItem) -> List[AclReference]:
        """Extract ACLs for Slack conversation. Defaults to engineering & backend access."""
        return [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=item.id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_engineering",
                permission="READ",
            ),
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=item.id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_backend",
                permission="READ",
            ),
        ]
