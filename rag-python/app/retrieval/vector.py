"""Vector retrieval component for hybrid RAG pipeline (AD-02, AD-06).

Executes vector similarity search using PostgreSQL pgvector (<=> cosine distance)
or deterministic in-memory cosine similarity fallback.
"""

import logging
import math
from typing import List, Optional

from app.contracts.rag_search import RagSearchResultItem
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.indexing.repository import KnowledgeRepository

logger = logging.getLogger(__name__)


class VectorRetriever:
    """Retrieves ranked chunk candidates using pgvector or in-memory cosine similarity."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        embedding_provider: Optional[EmbeddingProvider] = None,
        default_user_id: Optional[str] = None,
        default_group_ids: Optional[List[str]] = None,
    ):
        self.repository = repository
        self.embedding_provider = embedding_provider or get_embedding_provider()
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
        """Execute vector similarity search for a text query.

        Empty or whitespace queries return [] immediately without calling the embedding provider.
        """
        if not query or not query.strip():
            return []

        logger.debug("vector_search_generating_embedding query=%s", query)
        query_embedding = self.embedding_provider.embed_query(query)
        return self.search_by_vector(
            query_embedding=query_embedding,
            limit=limit,
            source_types=source_types,
            user_id=user_id,
            group_ids=group_ids,
        )

    def search_by_vector(
        self,
        query_embedding: List[float],
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Execute vector similarity search using a pre-computed embedding vector enforcing ACLs."""
        expected_dim = self.embedding_provider.dimension
        if len(query_embedding) != expected_dim:
            raise ValueError(
                f"Query embedding dimension mismatch: expected {expected_dim}, got {len(query_embedding)}"
            )

        q_norm = math.sqrt(sum(x * x for x in query_embedding))
        if q_norm == 0.0 or math.isclose(q_norm, 0.0, abs_tol=1e-12):
            return []

        effective_user_id = user_id if user_id is not None else self.default_user_id
        effective_group_ids = group_ids if group_ids is not None else self.default_group_ids

        logger.debug(
            "vector_search_executing limit=%d source_types=%s user_id=%s groups=%s",
            limit,
            source_types,
            effective_user_id,
            effective_group_ids,
        )
        return self.repository.search_vector(
            query_embedding=query_embedding,
            limit=limit,
            source_types=source_types,
            user_id=effective_user_id,
            group_ids=effective_group_ids,
        )
