"""Deterministic query classification for hybrid retrieval (AD-06).

Classifies queries into four core categories:
1. IDENTIFIER: Exact ticket IDs (e.g. DC-8692), commit hashes, or PR references.
2. KEYWORD: Discrete technical keywords, symbols, or phrases without conversational structure.
3. SEMANTIC: Natural language questions, explanations, or conceptual inquiries.
4. MIXED: Identifiers combined with natural language semantic inquiries or descriptive keywords.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Set

from app.normalization.common import extract_ticket_ids

# Commit hash pattern: 7 to 40 hex characters.
# Requires at least one digit and one hex character if length < 40, or 40 hex characters.
COMMIT_HASH_PATTERN = re.compile(
    r"\b(?=[0-9a-fA-F]{7,40}\b)(?:(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*[0-9])[0-9a-fA-F]{7,40}|[0-9a-fA-F]{40})\b"
)

# Pull Request pattern: matches #123, PR #123, PR 123, or pull request #123
PR_PATTERN = re.compile(
    r"(?:^|[\s,;:(])(?:pull\s+request|pr)?\s*#?(\d{1,6})\b",
    re.IGNORECASE,
)

# Semantic question words and interrogatives
QUESTION_INDICATORS: Set[str] = {
    "why",
    "how",
    "what",
    "where",
    "when",
    "who",
    "which",
    "whom",
    "explain",
    "describe",
    "summarize",
    "clarify",
    "details",
    "overview",
}

# Question auxiliary starters (e.g. "is validation synchronous?", "does the service handle...")
QUESTION_AUXILIARIES: Set[str] = {
    "can",
    "could",
    "would",
    "should",
    "is",
    "are",
    "was",
    "were",
    "does",
    "do",
    "did",
    "will",
}

# Words typically indicating an identifier lookup command rather than substantive semantic content
IDENTIFIER_BOILERPLATE: Set[str] = {
    "ticket",
    "tickets",
    "issue",
    "issues",
    "pr",
    "prs",
    "pull",
    "request",
    "commit",
    "commits",
    "sha",
    "hash",
    "ref",
    "id",
    "show",
    "get",
    "find",
    "lookup",
    "view",
    "check",
    "for",
    "the",
    "a",
    "an",
    "in",
    "and",
    "or",
    "to",
    "of",
}

# General stop words used to count substantive content words
STOP_WORDS: Set[str] = {
    "the", "a", "an", "in", "on", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "in", "out", "on",
    "off", "over", "under", "again", "further", "then", "once", "and",
    "but", "or", "because", "as", "until", "while", "of", "it", "its",
    "this", "that", "these", "those",
}


class QueryType(str, Enum):
    """Core query classification types per AD-06."""
    IDENTIFIER = "IDENTIFIER"
    KEYWORD = "KEYWORD"
    SEMANTIC = "SEMANTIC"
    MIXED = "MIXED"


@dataclass(frozen=True)
class ClassificationResult:
    """Structured result of deterministic query classification."""
    query: str
    query_type: QueryType
    ticket_ids: List[str] = field(default_factory=list)
    commit_hashes: List[str] = field(default_factory=list)
    pr_numbers: List[str] = field(default_factory=list)
    extracted_identifiers: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    has_question_intent: bool = False

    @property
    def is_identifier(self) -> bool:
        """Returns True if the query has identifier components (IDENTIFIER or MIXED)."""
        return self.query_type in (QueryType.IDENTIFIER, QueryType.MIXED)

    @property
    def is_semantic(self) -> bool:
        """Returns True if the query requires semantic search (SEMANTIC or MIXED)."""
        return self.query_type in (QueryType.SEMANTIC, QueryType.MIXED)


class QueryClassifier:
    """Deterministic, rule-based classifier detecting identifier, keyword, semantic, and mixed queries."""

    def classify(self, query: str) -> ClassificationResult:
        raw_query = query or ""
        normalized = raw_query.strip()

        if not normalized:
            return ClassificationResult(
                query=raw_query,
                query_type=QueryType.KEYWORD,
            )

        # 1. Detect ticket IDs (e.g. DC-8692 or dc-8692)
        ticket_ids = extract_ticket_ids(normalized.upper())

        # 2. Detect commit hashes
        commit_hashes = sorted(list(set(COMMIT_HASH_PATTERN.findall(normalized))))

        # 3. Detect PR numbers (#123, PR #45)
        # Avoid treating standalone small numbers in general text as PRs unless explicitly prefixed with # or PR
        pr_numbers: List[str] = []
        for match in re.finditer(r"(?:pull\s+request|pr\s*#?|#)(\d{1,6})\b", normalized, re.IGNORECASE):
            pr_numbers.append(match.group(1))
        pr_numbers = sorted(list(set(pr_numbers)))

        # Consolidate all extracted identifiers
        all_identifiers: List[str] = []
        all_identifiers.extend(ticket_ids)
        all_identifiers.extend(commit_hashes)
        for pr in pr_numbers:
            all_identifiers.append(f"PR-#{pr}")

        has_identifiers = len(all_identifiers) > 0

        # 4. Tokenize and analyze query words
        tokens = [t.lower() for t in re.findall(r"\b[\w-]+\b", normalized)]

        # Check for interrogatives / question indicators
        has_question_word = any(t in QUESTION_INDICATORS for t in tokens)
        has_question_mark = "?" in normalized

        first_token = tokens[0] if tokens else ""
        starts_with_auxiliary = first_token in QUESTION_AUXILIARIES and len(tokens) >= 3

        has_question_intent = has_question_word or has_question_mark or starts_with_auxiliary

        # 5. Extract keywords (filtered from stop words and punctuation)
        clean_keywords = [
            t for t in tokens
            if t not in STOP_WORDS
            and t not in IDENTIFIER_BOILERPLATE
            and not any(t == tid.lower() for tid in ticket_ids)
            and not any(t == ch.lower() for ch in commit_hashes)
        ]

        # Content words excluding identifier boilerplate
        substantive_tokens = [
            t for t in tokens
            if t not in IDENTIFIER_BOILERPLATE
            and t not in STOP_WORDS
            and not any(t == tid.lower() for tid in ticket_ids)
            and not any(t == ch.lower() for ch in commit_hashes)
        ]

        # 6. Classification rules
        if has_identifiers:
            # If the query contains question intent or substantive non-boilerplate content, it is MIXED
            if has_question_intent or len(substantive_tokens) >= 2:
                q_type = QueryType.MIXED
            else:
                q_type = QueryType.IDENTIFIER
        else:
            # No identifiers present
            if has_question_intent or len(tokens) >= 6:
                q_type = QueryType.SEMANTIC
            else:
                q_type = QueryType.KEYWORD

        return ClassificationResult(
            query=raw_query,
            query_type=q_type,
            ticket_ids=ticket_ids,
            commit_hashes=commit_hashes,
            pr_numbers=pr_numbers,
            extracted_identifiers=all_identifiers,
            keywords=clean_keywords,
            has_question_intent=has_question_intent,
        )
