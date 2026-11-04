"""SentenceTransformer embedding provider using local Hugging Face models."""

import logging
from typing import List, Optional

import numpy as np

from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Real vector embedding generator powered by sentence-transformers."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        dimension: Optional[int] = None,
    ):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        if hasattr(self.model, "get_embedding_dimension"):
            base_dim = self.model.get_embedding_dimension()
        else:
            base_dim = self.model.get_sentence_embedding_dimension()
        self._base_dimension = base_dim
        # If dimension is specified (e.g. 1536 for pgvector schema compatibility),
        # pad or truncate embeddings to match the expected schema dimension.
        self._dimension = dimension if dimension is not None else base_dim

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
        embedding = self.model.encode(query, normalize_embeddings=True)
        if isinstance(embedding, list):
            embedding = np.array(embedding)
        return self._adjust_dimension(embedding)
