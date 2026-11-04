"""SentenceTransformer embedding provider using local Hugging Face models."""

from collections import OrderedDict
import logging
from typing import Dict, List, Optional

import numpy as np

from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Real vector embedding generator powered by sentence-transformers."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        dimension: Optional[int] = None,
        cache_size: int = 1024,
    ):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        try:
            self.model = SentenceTransformer(model_name, local_files_only=True)
        except Exception:
            self.model = SentenceTransformer(model_name)
        if hasattr(self.model, "get_embedding_dimension"):
            base_dim = self.model.get_embedding_dimension()
        else:
            base_dim = self.model.get_sentence_embedding_dimension()
        self._base_dimension = base_dim
        # If dimension is specified (e.g. 1536 for pgvector schema compatibility),
        # pad or truncate embeddings to match the expected schema dimension.
        self._dimension = dimension if dimension is not None else base_dim
        self._cache_size = cache_size
        self._query_cache: OrderedDict[str, List[float]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def cache_stats(self) -> Dict[str, int]:
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": len(self._query_cache),
            "max_size": self._cache_size,
        }

    def clear_cache(self) -> None:
        self._query_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def dimension(self) -> int:
        return self._dimension

    def _adjust_dimension(self, vector: np.ndarray) -> List[float]:
        if len(vector) == self._dimension:
            return vector.tolist()
        if len(vector) < self._dimension:
            padded = np.pad(vector, (0, self._dimension - len(vector)))
            return padded.tolist()
        # len(vector) > self._dimension: truncate and re-normalize
        truncated = vector[: self._dimension]
        norm = np.linalg.norm(truncated)
        if norm > 0:
            truncated = truncated / norm
        return truncated.tolist()

    def embed_texts(self, texts: List[str], batch_size: int = 256) -> List[List[float]]:
        if not texts:
            return []
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if isinstance(embeddings, list):
            embeddings = np.array(embeddings)
        return [self._adjust_dimension(emb) for emb in embeddings]

    def embed_query(self, query: str) -> List[float]:
        if self._cache_size > 0 and query in self._query_cache:
            self._cache_hits += 1
            self._query_cache.move_to_end(query)
            return self._query_cache[query]

        self._cache_misses += 1
        embedding = self.model.encode(query, normalize_embeddings=True)
        if isinstance(embedding, list):
            embedding = np.array(embedding)
        result = self._adjust_dimension(embedding)

        if self._cache_size > 0:
            if len(self._query_cache) >= self._cache_size:
                self._query_cache.popitem(last=False)
            self._query_cache[query] = result

        return result
