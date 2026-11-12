"""Optional neural Cross-Encoder reranking stage over top-K ACL-filtered candidates."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from app.contracts.rag_search import RagSearchResultItem

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """Reranks ACL-filtered retrieval candidates using sentence-transformers CrossEncoder."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        top_k: int = 50,
        model: Optional[Any] = None,
    ):
        self.model_name = model_name
        self.top_k = max(1, top_k)
        self._model = model

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            logger.info("loading_cross_encoder model=%s", self.model_name)
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        candidates: List[RagSearchResultItem],
        limit: Optional[int] = None,
    ) -> List[RagSearchResultItem]:
        """Score up to top_k ACL-filtered candidates and return re-ordered items."""
        if not candidates or not query or not query.strip():
            return candidates[:limit] if limit is not None else list(candidates)

        pool = candidates[: self.top_k]
        pairs = [(query.strip(), f"{item.title}\n{item.snippet}".strip()) for item in pool]
        raw_scores = self._get_model().predict(pairs)

        rescored = [
            item.model_copy(update={"score": round(float(score), 6)})
            for item, score in zip(pool, raw_scores)
        ]
        rescored.sort(key=lambda item: (-item.score, item.chunk_id))
        return rescored[:limit] if limit is not None else rescored
