"""Embedding provider abstraction (AD-05, AD-06)."""

from abc import ABC, abstractmethod
from typing import List


class EmbeddingProvider(ABC):
    """Abstract vector embedding generator."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension produced by this provider."""
        ...

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of document chunks."""
        ...

    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query string."""
        results = self.embed_texts([query])
        return results[0]
