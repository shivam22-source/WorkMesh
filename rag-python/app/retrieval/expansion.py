"""Enterprise domain acronym and synonym expansion for lexical retrieval."""

import re
from typing import Dict, Set

# Domain-specific abbreviation to expanded synonyms mapping
ENTERPRISE_ACRONYM_MAP: Dict[str, Set[str]] = {
    "pr": {"pull request"},
    "prs": {"pull requests"},
    "jwt": {"token", "authentication"},
    "k8s": {"kubernetes"},
    "acl": {"permissions", "access control"},
    "acls": {"permissions", "access control"},
    "db": {"database"},
    "repo": {"repository"},
    "repos": {"repositories"},
    "auth": {"authentication", "authorization"},
}


def expand_query_terms(query: str) -> str:
    """Expand enterprise technical acronyms in query for higher lexical recall.

    Preserves original query tokens while appending disambiguated synonyms.
    """
    if not query or not query.strip():
        return query

    tokens = re.findall(r"\b[\w-]+\b", query)
    expansions: Set[str] = set()

    for token in tokens:
        lower_token = token.lower()
        if lower_token in ENTERPRISE_ACRONYM_MAP:
            expansions.update(ENTERPRISE_ACRONYM_MAP[lower_token])

    if not expansions:
        return query

    expanded_tail = " ".join(sorted(expansions))
    return f"{query} {expanded_tail}"
