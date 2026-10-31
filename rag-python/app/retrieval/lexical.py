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

    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    def search(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Execute lexical full-text search returning ranked RagSearchResultItem records."""
        if not query or not query.strip():
            return []

        logger.debug("lexical_search_executing query=%s limit=%d source_types=%s", query, limit, source_types)
        return self.repository.search_lexical(
            query=query,
            limit=limit,
            source_types=source_types,
        )
