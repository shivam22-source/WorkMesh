"""Deterministic mock embedding provider for tests, fixtures, and offline runs."""

import hashlib
import math
from typing import List

from app.embeddings.base import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """Generates deterministic, unit-length normalized vector embeddings based on text hashes.

    Ensures identical strings produce identical embeddings without requiring network
    or external API keys.
    """

    def __init__(self, dimension: int = 1536):
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed_single(self, text: str) -> List[float]:
        # Generate deterministic seed from text
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec: List[float] = []

        # Generate numbers deterministically
        for i in range(self._dimension):
            byte_val = h[i % len(h)]
            val = math.sin((byte_val + i) * 0.1)
            vec.append(val)

        # Normalize to unit length (L2 norm = 1.0) for cosine similarity
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_single(t) for t in texts]
