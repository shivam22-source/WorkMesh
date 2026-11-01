"""Email fixture adapter reading synthetic mailbox and thread records (AD-08).

Reuses SourceConnector directly without live network or external email dependencies.
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
from app.connectors.email.models import EmailAttachmentMeta

logger = logging.getLogger(__name__)


def parse_strict_utc_iso(ts_str: str) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware UTC datetime.

    Rejects timezone-naive strings and malformed formats.
    """
    if not isinstance(ts_str, str) or not ts_str.strip():
        raise ValueError("Timestamp must be a non-empty string")
    clean_str = ts_str.strip()
    clean_iso = clean_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(clean_iso)
    except Exception as e:
        raise ValueError(f"Malformed ISO-8601 timestamp '{ts_str}': {e}") from e

    if dt.tzinfo is None:
        raise ValueError(f"Naive timestamp rejected: explicit timezone offset required ('{ts_str}')")

    return dt.astimezone(timezone.utc)


_parse_utc_iso = parse_strict_utc_iso


class EmailFixtureAdapter(SourceConnector):
    """Deterministic fixture adapter reading synthetic emails from JSON."""

    def __init__(self, fixture_path: Optional[Path] = None):
        if fixture_path is None:
            base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
            self.fixture_path = base_dir / "data" / "fixtures" / "email" / "sample_email_data.json"
        else:
            self.fixture_path = Path(fixture_path)

        self._items: List[RawSourceItem] = []
        self._registries: Dict[str, Any] = {}
        self._loaded = False

    @property
    def source_type(self) -> SourceType:
        return SourceType.EMAIL

    def authenticate(self) -> bool:
        """Fixture adapter is authenticated if the fixture file exists."""
        return self.fixture_path.exists()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        if not self.fixture_path.exists():
            logger.warning("email_fixture_file_not_found path=%s", self.fixture_path)
            self._items = []
            self._registries = {}
            self._loaded = True
            return

        with open(self.fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._registries = data.get("registries", {})
        raw_messages = data.get("messages", [])
        items: List[RawSourceItem] = []

        for msg in raw_messages:
            msg_id = msg.get("id")
            created_at = _parse_utc_iso(msg.get("created_at", ""))
            updated_at = _parse_utc_iso(msg.get("updated_at", ""))

            # Attachment metadata only: filename, mime_type, size_bytes
            raw_attachments = msg.get("attachments", [])
            attachments = [
                EmailAttachmentMeta(
                    filename=a["filename"],
                    mime_type=a["mime_type"],
                    size_bytes=int(a["size_bytes"]),
                ).model_dump()
                for a in raw_attachments
                if "filename" in a and "mime_type" in a and "size_bytes" in a
            ]

            meta = {
                "mailbox": msg.get("mailbox", ""),
                "folder": msg.get("folder", "INBOX"),
                "message_id": msg.get("message_id", ""),
                "thread_id": msg.get("thread_id", ""),
                "in_reply_to": msg.get("in_reply_to"),
                "from_addr": msg.get("from_addr", ""),
                "to_addrs": msg.get("to_addrs", []),
                "cc_addrs": msg.get("cc_addrs", []),
                "attachments": attachments,
            }
            if msg.get("bcc_addrs"):
                meta["bcc_addrs"] = msg["bcc_addrs"]

            raw_item = RawSourceItem(
                id=msg_id,
                source_type=SourceType.EMAIL,
                source_id=msg.get("message_id", msg_id),
                source_url=msg.get("source_url", f"https://mail.company.internal/mail/messages/{msg_id}"),
                title=msg.get("subject", "No Subject"),
                author_id=msg.get("from_addr", "unknown"),
                raw_content=msg.get("body_text", ""),
                metadata=meta,
                created_at=created_at,
                updated_at=updated_at,
            )
            items.append(raw_item)

        # Sort chronologically by (updated_at, id)
        items.sort(key=lambda x: (x.updated_at, x.id))
        self._items = items
        self._loaded = True
        logger.info("loaded_email_fixtures count=%d from=%s", len(items), self.fixture_path)

    def list_changes(
        self, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Tuple[List[RawSourceItem], Optional[str]]:
        self._ensure_loaded()
        if not self._items:
            return [], cursor

        if cursor:
            # Parse compound cursor <ISO-TIMESTAMP>#<ID>
            if "#" in cursor:
                ts_part, id_part = cursor.split("#", 1)
            else:
                ts_part, id_part = cursor, ""

            cursor_dt = _parse_utc_iso(ts_part)
            cursor_id = id_part.strip()

            filtered: List[RawSourceItem] = []
            for item in self._items:
                item_dt = item.updated_at.astimezone(timezone.utc)
                if item_dt > cursor_dt:
                    filtered.append(item)
                elif item_dt == cursor_dt and item.id > cursor_id:
                    filtered.append(item)
        else:
            filtered = self._items

        if not filtered:
            return [], cursor

        batch = filtered[:limit] if limit and limit > 0 else filtered
        last_item = batch[-1]
        next_cursor = f"{last_item.updated_at.astimezone(timezone.utc).isoformat()}#{last_item.id}"
        return batch, next_cursor

    def fetch_item(self, item_id: str) -> Optional[RawSourceItem]:
        self._ensure_loaded()
        for item in self._items:
            if item.id == item_id or item.source_id == item_id:
                return item
        return None

    def build_source_link(self, item: RawSourceItem) -> str:
        """Returns the explicit fixture-provided source link."""
        return item.source_url

    def extract_acl(self, item: RawSourceItem) -> List[AclReference]:
        """Extracts deterministic per-message ACLs using explicit demo registries.

        Rules:
        - Sender's Sent Copy (folder == 'Sent'): SENDER ONLY receives READ access.
        - Received / Inbox Copy (folder != 'Sent'):
          - Sender receives READ access.
          - Mailbox owner receives READ access (if mapped).
          - To & Cc recipients receive READ access (if mapped to USER or GROUP).
          - Shared folder receives GROUP READ access (if mapped).
        - Deny-by-default: Unknown or unmapped addresses/folders produce ZERO ACL references.
        """
        self._ensure_loaded()

        emp_dir: Dict[str, str] = self._registries.get("employee_directory", {})
        group_aliases: Dict[str, str] = self._registries.get("group_aliases", {})
        mailboxes: Dict[str, Dict[str, str]] = self._registries.get("mailboxes", {})
        shared_folders: Dict[str, Dict[str, str]] = self._registries.get("shared_folders", {})

        meta = item.metadata
        from_addr = meta.get("from_addr", "")
        folder = meta.get("folder", "")
        mailbox = meta.get("mailbox", "")
        to_addrs: List[str] = meta.get("to_addrs", [])
        cc_addrs: List[str] = meta.get("cc_addrs", [])
        bcc_addrs: List[str] = meta.get("bcc_addrs", [])

        acls: List[AclReference] = []

        def add_user_if_mapped(email_addr: str) -> None:
            clean = email_addr.strip().lower()
            if clean in emp_dir:
                acls.append(
                    AclReference(
                        resource_type="SOURCE_RECORD",
                        resource_id=item.id,
                        principal_type=PrincipalType.USER,
                        principal_id=emp_dir[clean],
                        permission="READ",
                    )
                )

        def add_principal_for_recipient(email_addr: str) -> None:
            clean = email_addr.strip().lower()
            # Check user directory
            if clean in emp_dir:
                acls.append(
                    AclReference(
                        resource_type="SOURCE_RECORD",
                        resource_id=item.id,
                        principal_type=PrincipalType.USER,
                        principal_id=emp_dir[clean],
                        permission="READ",
                    )
                )
            # Check group distribution alias
            elif clean in group_aliases:
                acls.append(
                    AclReference(
                        resource_type="SOURCE_RECORD",
                        resource_id=item.id,
                        principal_type=PrincipalType.GROUP,
                        principal_id=group_aliases[clean],
                        permission="READ",
                    )
                )

        # 1. Sent Copy isolation: sender ONLY
        if folder == "Sent":
            add_user_if_mapped(from_addr)
        elif bcc_addrs and mailbox.strip().lower() in [b.strip().lower() for b in bcc_addrs]:
            # 2. BCC Recipient's Inbox Copy: Sender + BCC Recipient (mailbox owner) ONLY
            add_user_if_mapped(from_addr)
            add_user_if_mapped(mailbox)
        else:
            # 3. Received Copy: Sender + Mailbox Owner + To/Cc recipients + Shared Folder Group
            add_user_if_mapped(from_addr)

            # Mailbox owner
            clean_mailbox = mailbox.strip().lower()
            if clean_mailbox in mailboxes:
                owner_uid = mailboxes[clean_mailbox].get("owner_user_id")
                if owner_uid:
                    acls.append(
                        AclReference(
                            resource_type="SOURCE_RECORD",
                            resource_id=item.id,
                            principal_type=PrincipalType.USER,
                            principal_id=owner_uid,
                            permission="READ",
                        )
                    )

            # To recipients
            for addr in to_addrs:
                add_principal_for_recipient(addr)

            # Cc recipients
            for addr in cc_addrs:
                add_principal_for_recipient(addr)

            # Shared Folder
            clean_folder = folder.strip()
            if clean_folder in shared_folders:
                folder_gid = shared_folders[clean_folder].get("group_id")
                if folder_gid:
                    acls.append(
                        AclReference(
                            resource_type="SOURCE_RECORD",
                            resource_id=item.id,
                            principal_type=PrincipalType.GROUP,
                            principal_id=folder_gid,
                            permission="READ",
                        )
                    )

        # Deduplicate ACL references
        seen = set()
        deduped: List[AclReference] = []
        for acl in acls:
            key = (
                acl.resource_type,
                acl.resource_id,
                acl.principal_type.value if hasattr(acl.principal_type, "value") else str(acl.principal_type),
                acl.principal_id,
                acl.permission,
            )
            if key not in seen:
                seen.add(key)
                deduped.append(acl)

        return deduped
