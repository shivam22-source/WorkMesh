"""Tests for embedding provider interface and mock implementation."""

import math
from app.embeddings.factory import get_embedding_provider
from app.embeddings.mock_provider import MockEmbeddingProvider


def test_mock_embedding_provider_is_deterministic():
    provider = MockEmbeddingProvider(dimension=1536)

    text = "Why did we change the validation flow?"
    vec1 = provider.embed_query(text)
    vec2 = provider.embed_query(text)

    assert len(vec1) == 1536
    assert vec1 == vec2


def test_mock_embeddings_are_unit_normalized():
    provider = MockEmbeddingProvider(dimension=1536)
    vec = provider.embed_query("Payment validation fix DC-8692")

    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-5


def test_factory_returns_mock_by_default():
    provider = get_embedding_provider("mock")
    assert isinstance(provider, MockEmbeddingProvider)
    assert provider.dimension == 1536
