"""Common normalization utilities shared across sources."""

import re
from typing import List, Set

TICKET_PATTERN = re.compile(r"\b([A-Z]{2,10}-\d+)\b")


def extract_ticket_ids(text: str) -> List[str]:
    """Extract ticket identifiers (e.g. DC-8692) from unstructured text."""
    if not text:
        return []
    matches: Set[str] = set(TICKET_PATTERN.findall(text))
    return sorted(list(matches))
