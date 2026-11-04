"""Factory for resolving the active embedding provider."""

import logging
from typing import Optional

from app.common.config import get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider

logger = logging.getLogger(__name__)


def get_embedding_provider(name: Optional[str] = None) -> EmbeddingProvider:
    settings = get_settings()
    provider_name = (name or settings.embedding_provider).lower()

    if provider_name == "mock":
        return MockEmbeddingProvider(dimension=settings.embedding_dimension)

    if provider_name in ("sentence-transformers", "sentence_transformers", "local", "minilm"):
        return SentenceTransformerEmbeddingProvider(
            model_name=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )

    if provider_name == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "OpenAI embedding provider requested but openai_api_key is missing. "
                "Silently falling back to mock is disabled."
            )
        raise NotImplementedError(
            "OpenAI embedding provider is not implemented in this deployment. "
            "Silently falling back to mock is disabled."
        )

    raise ValueError(f"Unknown embedding provider: {provider_name}")
