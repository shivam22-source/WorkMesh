"""Models for email source items, attachments, and metadata."""

from typing import List, Optional
from pydantic import BaseModel, Field


class EmailAttachmentMeta(BaseModel):
    """Attachment reference metadata without binary contents or invented hashes."""

    filename: str
    mime_type: str
    size_bytes: int


class EmailMessageRaw(BaseModel):
    """Raw parsed email message representing a distinct mailbox copy."""

    id: str
    message_id: str
    thread_id: str
    in_reply_to: Optional[str] = None
    mailbox: str
    folder: str
    from_addr: str
    to_addrs: List[str] = Field(default_factory=list)
    cc_addrs: List[str] = Field(default_factory=list)
    bcc_addrs: Optional[List[str]] = None
    subject: str
    body_text: str
    attachments: List[EmailAttachmentMeta] = Field(default_factory=list)
    source_url: str
    created_at: str
    updated_at: str
