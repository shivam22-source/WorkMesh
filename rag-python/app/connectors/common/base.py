"""Base abstraction for source connectors (AD-07).

Every connector (GitHub, Slack, Email) exposes the same conceptual interface:
- authenticate()
- list_changes(cursor)
- fetch_item(id)
- build_source_link(item)
- extract_acl(item)
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from app.connectors.common.models import AclReference, RawSourceItem, SourceType


class SourceConnector(ABC):
    """Abstract connector interface shared across all knowledge sources."""

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """The source system type."""
        ...

    @abstractmethod
    def authenticate(self) -> bool:
        """Verify credentials or connectivity to the source system."""
        ...

    @abstractmethod
    def list_changes(
        self, cursor: Optional[str] = None
    ) -> Tuple[List[RawSourceItem], Optional[str]]:
        """List changed or new items since the provided cursor checkpoint.

        Returns:
            Tuple of (items, next_cursor). If no further items exist, returns the latest cursor.
        """
        ...

    @abstractmethod
    def fetch_item(self, item_id: str) -> Optional[RawSourceItem]:
        """Fetch a single raw item by its unique source identifier."""
        ...

    @abstractmethod
    def build_source_link(self, item: RawSourceItem) -> str:
        """Build a verifiable permanent link back to the original source item."""
        ...

    @abstractmethod
    def extract_acl(self, item: RawSourceItem) -> List[AclReference]:
        """Extract access control permissions associated with this source item."""
        ...
