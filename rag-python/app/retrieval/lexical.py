"""Lexical (full-text) retrieval component for hybrid RAG pipeline (AD-02, AD-06).

Executes full-text keyword and identifier retrieval using PostgreSQL chunks.tsv or in-memory fallback.
"""

import logging
from typing import List, Optional

from app.contracts.rag_search import RagSearchResultItem
from app.indexing.repository import KnowledgeRepository

logger = logging.getLogger(__name__)


class LexicalRetriever:
    """Retrieves ranked chunk candidates using PostgreSQL full-text search or in-memory fallback."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        default_user_id: Optional[str] = None,
        default_group_ids: Optional[List[str]] = None,
    ):
        self.repository = repository
        self.default_user_id = default_user_id
        self.default_group_ids = default_group_ids

    def search(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Execute lexical full-text search returning ranked RagSearchResultItem records enforcing ACLs."""
        if not query or not query.strip():
            return []

        effective_user_id = user_id if user_id is not None else self.default_user_id
        effective_group_ids = group_ids if group_ids is not None else self.default_group_ids

        logger.debug(
            "lexical_search_executing query=%s limit=%d source_types=%s user_id=%s groups=%s",
            query,
            limit,
            source_types,
            effective_user_id,
            effective_group_ids,
        )
        return self.repository.search_lexical(
            query=query,
            limit=limit,
            source_types=source_types,
            user_id=effective_user_id,
            group_ids=effective_group_ids,
        )
