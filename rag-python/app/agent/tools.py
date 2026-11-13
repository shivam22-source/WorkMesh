"""Read-only agent tools with strict ACL enforcement and caller identity propagation.

Invariants:
- All tools are strictly READ-ONLY.
- Every tool call executes with the authenticated caller's identity (user_id and group_ids).
- ACL filtering is enforced at the database/repository boundary for every tool.
- Unauthorized entities, documents, or threads return empty/denied results without leaking metadata.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.contracts.rag_search import RagSearchResultItem
from app.indexing.repository import KnowledgeRepository
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)


class AgentTools:
    """Read-only toolset bound to an authenticated caller's identity."""

    def __init__(
        self,
        retriever: HybridRetriever,
        repository: KnowledgeRepository,
        user_id: str,
        group_ids: List[str],
    ):
        self.retriever = retriever
        self.repository = repository
        self.user_id = user_id
        self.group_ids = group_ids

    def search(
        self,
        query: str,
        limit: int = 5,
        source_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search enterprise knowledge using ACL-filtered hybrid retrieval."""
        clean_limit = min(max(1, limit), 20)
        candidates = self.retriever.search(
            query=query,
            limit=clean_limit,
            source_types=source_types,
            user_id=self.user_id,
            group_ids=self.group_ids,
        )
        return [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "source_type": c.source_type,
                "title": c.title,
                "snippet": c.snippet,
                "url": c.source_url,
                "score": round(c.score, 4),
            }
            for c in candidates
        ]

    def get_document(self, document_id: str) -> Dict[str, Any]:
        """Retrieve a document by ID with ACL verification."""
        clean_id = (document_id or "").strip()
        if not clean_id:
            return {"found": False, "error": "document_id cannot be blank"}

        doc = self.repository.get_document(
            document_id=clean_id,
            user_id=self.user_id,
            group_ids=self.group_ids,
        )
        if not doc:
            return {"found": False, "error": "Document not found or access denied"}

        return {
            "found": True,
            "id": doc.id,
            "source_record_id": doc.source_record_id,
            "source_type": doc.source_type,
            "title": doc.title,
            "content": doc.content,
            "author": doc.author,
            "url": doc.url,
            "metadata": doc.metadata,
        }

    def get_related(
        self,
        entity_id: str,
        relationship_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve related entities and relationships with ACL projection."""
        clean_id = (entity_id or "").strip()
        if not clean_id:
            return []

        rel_tuples = self.repository.get_relationships_for_entity(
            entity_id=clean_id,
            relationship_type=relationship_type,
            user_id=self.user_id,
            group_ids=self.group_ids,
        )

        return [
            {
                "relationship_type": rel.relationship_type,
                "source_entity_id": rel.source_entity_id,
                "target_entity_id": ent.id,
                "target_entity_type": ent.entity_type,
                "metadata": ent.metadata,
            }
            for rel, ent in rel_tuples
        ]

    def get_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> List[Dict[str, Any]]:
        """Retrieve Slack thread messages with ACL enforcement."""
        clean_channel = (channel_id or "").strip()
        clean_ts = (thread_ts or "").strip()
        if not clean_channel or not clean_ts:
            return []

        chunks = self.repository.get_thread(
            channel_id=clean_channel,
            thread_ts=clean_ts,
            user_id=self.user_id,
            group_ids=self.group_ids,
        )

        return [
            {
                "chunk_id": c.id,
                "document_id": c.document_id,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "metadata": c.metadata,
            }
            for c in chunks
        ]
