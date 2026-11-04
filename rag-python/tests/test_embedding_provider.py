"""Tests for embedding provider interface, mock implementation, and sentence-transformers."""

import math
import pytest
from app.embeddings.factory import get_embedding_provider
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider


def test_mock_embedding_provider_is_deterministic():
    provider = MockEmbeddingProvider(dimension=384)

    text = "Why did we change the validation flow?"
    vec1 = provider.embed_query(text)
    vec2 = provider.embed_query(text)

    assert len(vec1) == 384
    assert vec1 == vec2


def test_mock_embeddings_are_unit_normalized():
    provider = MockEmbeddingProvider(dimension=384)
    vec = provider.embed_query("Payment validation fix DC-8692")

    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-5


def test_factory_returns_mock_when_explicitly_requested():
    provider = get_embedding_provider("mock")
    assert isinstance(provider, MockEmbeddingProvider)
    assert provider.dimension == 384


def test_factory_returns_mock_by_default_in_tests():
    provider = get_embedding_provider()
    assert isinstance(provider, MockEmbeddingProvider)
    assert provider.dimension == 384


@pytest.mark.real_model
def test_factory_returns_sentence_transformers_when_configured(monkeypatch):
    from app.common.config import get_settings
    monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence-transformers")
    get_settings.cache_clear()
    try:
        provider = get_embedding_provider()
        assert isinstance(provider, SentenceTransformerEmbeddingProvider)
        assert provider.dimension == 384
    finally:
        get_settings.cache_clear()


@pytest.mark.real_model
def test_factory_returns_sentence_transformers():
    provider = get_embedding_provider("sentence-transformers")
    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.dimension == 384

    vec = provider.embed_query("Payment validation fix DC-8692")
    assert len(vec) == 384
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-5

    # Semantic similarity: related phrases should have higher cosine similarity than unrelated
    v1 = provider.embed_query("payment card validation failure")
    v2 = provider.embed_query("credit card checkout error")
    v3 = provider.embed_query("completely unrelated gardening instructions")

    sim_related = sum(a * b for a, b in zip(v1, v2))
    sim_unrelated = sum(a * b for a, b in zip(v1, v3))
    assert sim_related > sim_unrelated


@pytest.mark.real_model
def test_sentence_transformer_dimension_mismatch_raises_error():
    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        SentenceTransformerEmbeddingProvider(dimension=1536)


def test_factory_openai_no_longer_falls_back_to_mock():
    with pytest.raises((ValueError, NotImplementedError)):
        get_embedding_provider("openai")


def test_factory_unknown_provider_raises_error():
    with pytest.raises(ValueError):
        get_embedding_provider("nonexistent_provider_xyz")
