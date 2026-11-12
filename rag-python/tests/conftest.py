"""Global test configuration and fixtures for pytest."""

import os

import pytest

# Force mock embedding provider for offline test execution
os.environ["EMBEDDING_PROVIDER"] = "mock"

# Default test suite runs in dev mode unless overridden
os.environ.setdefault("AUTH_MODE", "dev")


def is_model_cached(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> bool:
    """Check if the sentence-transformers model exists in local cache without network access."""
    try:
        from sentence_transformers import SentenceTransformer
        _ = SentenceTransformer(model_name, local_files_only=True)
        return True
    except Exception:
        return False


def pytest_runtest_setup(item):
    """Automatically skip tests marked with real_model if weights are not cached locally."""
    if "real_model" in item.keywords:
        if not is_model_cached():
            pytest.skip("SentenceTransformer model weights not found in local offline cache")
