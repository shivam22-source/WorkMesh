"""Factory for resolving the active embedding provider."""

import logging
from typing import Optional

from app.common.config import get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.mock_provider import MockEmbeddingProvider

logger = logging.getLogger(__name__)


def get_embedding_provider(name: Optional[str] = None) -> EmbeddingProvider:
    settings = get_settings()
    provider_name = (name or settings.embedding_provider).lower()

    if provider_name == "mock":
        return MockEmbeddingProvider(dimension=settings.embedding_dimension)

    if provider_name == "openai":
        if not settings.openai_api_key:
            logger.warning("openai_key_missing_falling_back_to_mock")
            return MockEmbeddingProvider(dimension=settings.embedding_dimension)
        # Note: If openai package is installed in a future phase, it can be instantiated here
        logger.info("using_mock_embedding_provider_for_phase_2")
        return MockEmbeddingProvider(dimension=settings.embedding_dimension)

    return MockEmbeddingProvider(dimension=settings.embedding_dimension)
