"""Tests for SentenceTransformerEmbeddingProvider query LRU caching."""

import pytest

from app.embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider


@pytest.mark.real_model
def test_query_embedding_lru_cache():
    provider = SentenceTransformerEmbeddingProvider(cache_size=2)
    provider.clear_cache()

    q1 = "payment validation fix"
    q2 = "slack notification bug"
    q3 = "third unique query"

    # Miss 1
    v1_first = provider.embed_query(q1)
    assert provider.cache_stats["misses"] == 1
    assert provider.cache_stats["hits"] == 0

    # Hit 1
    v1_second = provider.embed_query(q1)
    assert provider.cache_stats["misses"] == 1
    assert provider.cache_stats["hits"] == 1
    assert v1_first == v1_second

    # Miss 2 (cache now holds q1, q2)
    provider.embed_query(q2)
    assert provider.cache_stats["size"] == 2

    # Miss 3 (evicts q1 because cache size is 2)
    provider.embed_query(q3)
    assert provider.cache_stats["size"] == 2

    # q1 was evicted, so embedding it again causes a miss
    provider.embed_query(q1)
    assert provider.cache_stats["misses"] == 4
    assert provider.cache_stats["hits"] == 1
