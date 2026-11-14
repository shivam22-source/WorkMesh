"""Tests for the pluggable LLM provider layer.

Covers:
- MockLlmProvider deterministic grounding and citation extraction.
- Factory function get_llm_provider() dispatching on LLM_PROVIDER.
- GeminiLlmProvider and AnthropicLlmProvider with mocked httpx (no real API calls).
- Retry with backoff on transient errors.
- Prompt content is never logged (only hashes).
- Missing API key raises RuntimeError.
- LLMProvider alias exists for naming convention.
"""

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.rag.llm import (
    AnthropicLlmProvider,
    GeminiLlmProvider,
    LLMProvider,
    LlmProvider,
    MockLlmProvider,
    _hash_prompt,
    _retry_with_backoff,
    get_llm_provider,
)
from app.rag.service import SYSTEM_PROMPT

# ---------------------------------------------------------------------------
# LLMProvider alias
# ---------------------------------------------------------------------------

def test_llm_provider_alias_is_same_as_llm_provider():
    """LLMProvider is an alias for LlmProvider (task naming convention)."""
    assert LLMProvider is LlmProvider


# ---------------------------------------------------------------------------
# MockLlmProvider (backward compat with existing tests)
# ---------------------------------------------------------------------------

def test_mock_llm_docstring_documents_pipeline_testing_purpose():
    """MockLlmProvider explicitly documents that it tests pipeline behavior and evidence containment."""
    doc = MockLlmProvider.__doc__
    assert doc is not None
    assert "pipeline wiring" in doc.lower()
    assert "does not measure real llm quality" in doc.lower()


def test_mock_llm_generates_deterministic_grounded_answer_from_numbered_evidence():
    """MockLlmProvider deterministically extracts core factual sentences and cites [1] and [2]."""
    llm = MockLlmProvider()

    prompt = (
        "Question: why did DC-100 change validation?\n\n"
        "Numbered Evidence:\n"
        "[1] Source: GITHUB | Title: PR 101 | URL: https://github.com/101\n"
        "Snippet: Resolves ticket DC-100 with defensive checks in auth middleware.\n\n"
        "[2] Source: SLACK | Title: Slack Thread | URL: https://slack.com/1\n"
        "Snippet: Discussing DC-100 resolution: team agreed to reject unauthenticated requests early.\n\n"
        "Answer:"
    )

    resp1 = llm.generate(SYSTEM_PROMPT, prompt)
    resp2 = llm.generate(SYSTEM_PROMPT, prompt)

    # Determinism
    assert resp1.content == resp2.content
    assert resp1.model == "mock-grounded-v1"

    # Grounded citations
    assert "[1]" in resp1.content
    assert "[2]" in resp1.content
    assert "Resolves ticket DC-100 with defensive checks in auth middleware." in resp1.content
    assert "Discussing DC-100 resolution: team agreed to reject unauthenticated requests early." in resp1.content


def test_mock_llm_handles_empty_evidence_with_insufficient_message():
    """When no numbered evidence is supplied in prompt, returns standard insufficient evidence text."""
    llm = MockLlmProvider()
    prompt = "Question: what is the secret project?\n\nNumbered Evidence:\n\nAnswer:"

    resp = llm.generate(SYSTEM_PROMPT, prompt)
    assert "not have sufficient" in resp.content.lower()
    assert "[1]" not in resp.content


# ---------------------------------------------------------------------------
# get_llm_provider factory
# ---------------------------------------------------------------------------

def test_factory_returns_mock_by_default():
    """Default LLM_PROVIDER='mock' returns MockLlmProvider."""
    settings = MagicMock()
    settings.llm_provider = "mock"
    settings.llm_model = ""
    settings.llm_timeout_seconds = 30
    settings.llm_max_retries = 3
    settings.llm_max_output_tokens = 1024

    provider = get_llm_provider(settings)
    assert isinstance(provider, MockLlmProvider)


def test_factory_gemini_requires_api_key():
    """Selecting gemini without GEMINI_API_KEY raises RuntimeError."""
    settings = MagicMock()
    settings.llm_provider = "gemini"
    settings.llm_model = "gemini-2.0-flash"
    settings.gemini_api_key = None

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        get_llm_provider(settings)


def test_factory_gemini_requires_model():
    """Selecting gemini without LLM_MODEL raises RuntimeError."""
    settings = MagicMock()
    settings.llm_provider = "gemini"
    settings.llm_model = ""
    settings.gemini_api_key = "test-key"

    with pytest.raises(RuntimeError, match="LLM_MODEL"):
        get_llm_provider(settings)


def test_factory_anthropic_requires_api_key():
    """Selecting anthropic without ANTHROPIC_API_KEY raises RuntimeError."""
    settings = MagicMock()
    settings.llm_provider = "anthropic"
    settings.llm_model = "claude-sonnet-4-20250514"
    settings.anthropic_api_key = None

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_llm_provider(settings)


def test_factory_anthropic_requires_model():
    """Selecting anthropic without LLM_MODEL raises RuntimeError."""
    settings = MagicMock()
    settings.llm_provider = "anthropic"
    settings.llm_model = ""
    settings.anthropic_api_key = "test-key"

    with pytest.raises(RuntimeError, match="LLM_MODEL"):
        get_llm_provider(settings)


def test_factory_returns_gemini_provider_with_valid_config():
    """Factory returns GeminiLlmProvider when settings are complete."""
    settings = MagicMock()
    settings.llm_provider = "gemini"
    settings.llm_model = "gemini-2.0-flash"
    settings.llm_timeout_seconds = 15
    settings.llm_max_retries = 2
    settings.llm_max_output_tokens = 512
    settings.gemini_api_key = "test-gemini-key"

    provider = get_llm_provider(settings)
    assert isinstance(provider, GeminiLlmProvider)
    assert provider.model == "gemini-2.0-flash"


def test_factory_returns_anthropic_provider_with_valid_config():
    """Factory returns AnthropicLlmProvider when settings are complete."""
    settings = MagicMock()
    settings.llm_provider = "anthropic"
    settings.llm_model = "claude-sonnet-4-20250514"
    settings.llm_timeout_seconds = 20
    settings.llm_max_retries = 2
    settings.llm_max_output_tokens = 2048
    settings.anthropic_api_key = "test-anthropic-key"

    provider = get_llm_provider(settings)
    assert isinstance(provider, AnthropicLlmProvider)
    assert provider.model == "claude-sonnet-4-20250514"


# ---------------------------------------------------------------------------
# GeminiLlmProvider with mocked httpx
# ---------------------------------------------------------------------------

def test_gemini_provider_calls_rest_api_and_parses_response():
    """GeminiLlmProvider sends correct payload and parses the response."""
    provider = GeminiLlmProvider(
        model="gemini-2.0-flash",
        api_key="test-key",
        timeout=10,
        max_retries=1,
        max_output_tokens=256,
    )

    mock_response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"),
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "The answer is 42. [1]"}],
                        "role": "model",
                    }
                }
            ]
        },
    )

    with patch.object(provider._client, "post", return_value=mock_response) as mock_post:
        result = provider.generate("Be helpful.", "What is the answer?")

    assert result.content == "The answer is 42. [1]"
    assert result.model == "gemini-2.0-flash"

    call_args = mock_post.call_args
    assert "generativelanguage.googleapis.com" in call_args[0][0]
    assert call_args[1]["params"] == {"key": "test-key"}
    payload = call_args[1]["json"]
    assert payload["system_instruction"]["parts"][0]["text"] == "Be helpful."
    assert payload["contents"][0]["parts"][0]["text"] == "What is the answer?"
    assert payload["generationConfig"]["maxOutputTokens"] == 256


# ---------------------------------------------------------------------------
# AnthropicLlmProvider with mocked httpx
# ---------------------------------------------------------------------------

def test_anthropic_provider_calls_rest_api_and_parses_response():
    """AnthropicLlmProvider sends correct payload and parses the response."""
    provider = AnthropicLlmProvider(
        model="claude-sonnet-4-20250514",
        api_key="test-key",
        timeout=10,
        max_retries=1,
        max_output_tokens=512,
    )

    mock_response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        json={
            "content": [{"type": "text", "text": "Evidence shows X. [1]"}],
            "model": "claude-sonnet-4-20250514",
            "role": "assistant",
        },
    )

    with patch.object(provider._client, "post", return_value=mock_response) as mock_post:
        result = provider.generate("Be grounded.", "What happened?")

    assert result.content == "Evidence shows X. [1]"
    assert result.model == "claude-sonnet-4-20250514"

    call_args = mock_post.call_args
    assert "api.anthropic.com" in call_args[0][0]
    headers = call_args[1]["headers"]
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    payload = call_args[1]["json"]
    assert payload["system"] == "Be grounded."
    assert payload["messages"][0]["content"] == "What happened?"
    assert payload["max_tokens"] == 512


# ---------------------------------------------------------------------------
# Retry with backoff
# ---------------------------------------------------------------------------

def test_retry_succeeds_on_second_attempt():
    """_retry_with_backoff retries on failure and returns on success."""
    call_count = 0

    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RuntimeError("transient")
        return "ok"

    result = _retry_with_backoff(flaky, max_retries=3, base_delay=0.01)
    assert result == "ok"
    assert call_count == 2


def test_retry_exhausts_retries_and_raises():
    """_retry_with_backoff raises after all retries are exhausted."""

    def always_fails():
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        _retry_with_backoff(always_fails, max_retries=2, base_delay=0.01)


# ---------------------------------------------------------------------------
# Prompt content never logged
# ---------------------------------------------------------------------------

def test_prompt_hash_is_deterministic():
    """_hash_prompt returns a stable hash for the same input."""
    h1 = _hash_prompt("sensitive enterprise data")
    h2 = _hash_prompt("sensitive enterprise data")
    assert h1 == h2
    assert len(h1) == 16


def test_gemini_provider_logs_hash_not_prompt(caplog):
    """GeminiLlmProvider logs prompt hash, never raw prompt content."""
    provider = GeminiLlmProvider(
        model="gemini-2.0-flash",
        api_key="test-key",
        timeout=10,
        max_retries=1,
    )

    mock_response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"),
        json={"candidates": [{"content": {"parts": [{"text": "answer"}]}}]},
    )

    secret_prompt = "The CEO's secret salary is $10M"
    with patch.object(provider._client, "post", return_value=mock_response):
        with caplog.at_level(logging.INFO, logger="app.rag.llm"):
            provider.generate("system", secret_prompt)

    log_text = caplog.text
    assert "secret salary" not in log_text
    assert "$10M" not in log_text
    assert "llm_generate" in log_text
    assert "sys_hash=" in log_text
    assert "usr_hash=" in log_text


def test_anthropic_provider_logs_hash_not_prompt(caplog):
    """AnthropicLlmProvider logs prompt hash, never raw prompt content."""
    provider = AnthropicLlmProvider(
        model="claude-sonnet-4-20250514",
        api_key="test-key",
        timeout=10,
        max_retries=1,
    )

    mock_response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        json={"content": [{"type": "text", "text": "answer"}]},
    )

    secret_prompt = "Employee SSN is 123-45-6789"
    with patch.object(provider._client, "post", return_value=mock_response):
        with caplog.at_level(logging.INFO, logger="app.rag.llm"):
            provider.generate("system", secret_prompt)

    log_text = caplog.text
    assert "123-45-6789" not in log_text
    assert "SSN" not in log_text
    assert "llm_generate" in log_text
