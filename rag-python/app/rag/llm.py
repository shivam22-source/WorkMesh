"""LLM provider abstraction layer with mock, Gemini, and Anthropic implementations.

Providers:
- **mock** (default): Deterministic offline provider for CI and testing.
  Extracts evidence from numbered blocks and formats citations. No network calls.
- **gemini**: Google Gemini API via REST (httpx). Requires ``GEMINI_API_KEY``.
- **anthropic**: Anthropic Claude API via REST (httpx). Requires ``ANTHROPIC_API_KEY``.

Security invariants:
- Prompt contents are **NEVER** logged. Only a SHA-256 digest is emitted for
  traceability. This prevents sensitive enterprise data from leaking into log
  aggregators.
- API keys are read exclusively from environment variables (via Settings).
- All network calls respect configurable timeouts with exponential backoff retry.

Configuration (all via environment / ``app.common.config.Settings``):
- ``LLM_PROVIDER``: ``mock`` | ``gemini`` | ``anthropic`` (default ``mock``).
- ``LLM_MODEL``: Provider-specific model identifier. Never hardcoded.
- ``LLM_TIMEOUT_SECONDS``: HTTP timeout (default 30).
- ``LLM_MAX_RETRIES``: Retry count with exponential backoff (default 3).
- ``LLM_MAX_OUTPUT_TOKENS``: Max tokens in completion (default 1024).
"""

import hashlib
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class LlmResponse(BaseModel):
    """Completion response from an LLM provider."""

    content: str
    model: str = "mock-grounded-v1"


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class LlmProvider(ABC):
    """Abstract LLM completion provider."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> LlmResponse:
        """Generate answer completion strictly from supplied prompt context."""
        ...


# Public alias matching task naming convention
LLMProvider = LlmProvider


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _hash_prompt(text: str) -> str:
    """SHA-256 digest of prompt content for safe audit logging.

    The full prompt must NEVER be logged — it may contain sensitive enterprise
    data. We emit only a short hash for correlation.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _retry_with_backoff(
    fn,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
):
    """Execute *fn()* with exponential backoff and jitter on transient errors.

    Uses stdlib only (no ``backoff`` or ``tenacity`` dependency).
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "llm_retry attempt=%d/%d delay=%.2fs err_type=%s",
                    attempt + 1,
                    max_retries,
                    delay,
                    type(exc).__name__,
                )
                time.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Mock implementation — used by CI (default)
# ---------------------------------------------------------------------------

class MockLlmProvider(LlmProvider):
    """Deterministic, offline mock LLM provider for grounded evidence synthesis.

    NOTE: This provider tests end-to-end pipeline wiring, prompt context propagation,
    evidence boundary containment, and citation mapping deterministically without external
    network calls, API keys, or non-deterministic variance. It does not measure real LLM quality.
    """

    def __init__(self, model_name: str = "mock-grounded-v1"):
        self.model_name = model_name

    def generate(self, system_prompt: str, user_prompt: str) -> LlmResponse:
        """Synthesize a grounded answer strictly from numbered evidence blocks in user_prompt."""
        evidence_blocks = self._parse_evidence_blocks(user_prompt)

        if not evidence_blocks:
            return LlmResponse(
                content="I do not have sufficient authorized documentation or evidence to answer this question.",
                model=self.model_name,
            )

        extracted_claims: List[str] = []
        for idx, snippet in evidence_blocks:
            first_sentence = self._extract_first_sentence(snippet)
            if first_sentence:
                extracted_claims.append(f"{first_sentence} [{idx}]")

        if not extracted_claims:
            return LlmResponse(
                content="I do not have sufficient authorized documentation or evidence to answer this question.",
                model=self.model_name,
            )

        answer_text = "According to the available evidence: " + " ".join(extracted_claims)
        return LlmResponse(content=answer_text, model=self.model_name)

    def _parse_evidence_blocks(self, prompt: str) -> List[tuple[int, str]]:
        """Parse numbered evidence items [1], [2] and their snippet content from the prompt."""
        # Pattern matching: [idx] Source: ... \n Snippet: {content}
        pattern = re.compile(
            r"\[(\d+)\]\s+Source:[^\n]+\nSnippet:\s*(.+?)(?=\n\n\[\d+\]|</untrusted_context_data>|</context>|\Z)",
            re.DOTALL,
        )
        blocks = []
        for match in pattern.finditer(prompt):
            idx = int(match.group(1))
            snippet = match.group(2).strip()
            blocks.append((idx, snippet))
        return blocks

    def _extract_first_sentence(self, text: str) -> str:
        """Extract first sentence or statement from a snippet text."""
        clean = " ".join(text.split()).strip()
        # Find sentence terminal: ., !, ?, or end
        m = re.search(r"^(.*?[.!?])(?:\s+|$)", clean)
        if m:
            return m.group(1).strip()
        # If no terminal punctuation, return up to first 120 chars cleanly
        if len(clean) > 120:
            last_space = clean[:120].rfind(" ")
            return clean[:last_space] + "..." if last_space > 0 else clean[:120] + "..."
        return clean


# ---------------------------------------------------------------------------
# Gemini implementation (REST via httpx)
# ---------------------------------------------------------------------------

class GeminiLlmProvider(LlmProvider):
    """Google Gemini API provider via REST.

    Uses the ``generativelanguage.googleapis.com`` v1beta endpoint.
    Model name is read from ``LLM_MODEL`` (e.g. ``gemini-2.0-flash``).
    API key from ``GEMINI_API_KEY``.
    """

    API_BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        model: str,
        api_key: str,
        timeout: int = 30,
        max_retries: int = 3,
        max_output_tokens: int = 1024,
    ):
        import httpx  # lazy — not needed in mock mode

        self.model = model
        self._api_key = api_key
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._client = httpx.Client(timeout=timeout)

    def generate(self, system_prompt: str, user_prompt: str) -> LlmResponse:
        logger.info(
            "llm_generate provider=gemini model=%s sys_hash=%s usr_hash=%s",
            self.model,
            _hash_prompt(system_prompt),
            _hash_prompt(user_prompt),
        )

        url = f"{self.API_BASE}/models/{self.model}:generateContent"
        payload: Dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": self._max_output_tokens,
                "temperature": 0.0,
            },
        }

        def _call() -> LlmResponse:
            resp = self._client.post(url, json=payload, params={"key": self._api_key})
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return LlmResponse(content=text, model=self.model)

        return _retry_with_backoff(_call, max_retries=self._max_retries)


# ---------------------------------------------------------------------------
# Anthropic implementation (REST via httpx)
# ---------------------------------------------------------------------------

class AnthropicLlmProvider(LlmProvider):
    """Anthropic Claude API provider via REST.

    Uses the ``api.anthropic.com/v1/messages`` endpoint.
    Model name is read from ``LLM_MODEL`` (e.g. ``claude-sonnet-4-20250514``).
    API key from ``ANTHROPIC_API_KEY``.
    """

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(
        self,
        model: str,
        api_key: str,
        timeout: int = 30,
        max_retries: int = 3,
        max_output_tokens: int = 1024,
    ):
        import httpx

        self.model = model
        self._api_key = api_key
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._client = httpx.Client(timeout=timeout)

    def generate(self, system_prompt: str, user_prompt: str) -> LlmResponse:
        logger.info(
            "llm_generate provider=anthropic model=%s sys_hash=%s usr_hash=%s",
            self.model,
            _hash_prompt(system_prompt),
            _hash_prompt(user_prompt),
        )

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._max_output_tokens,
            "temperature": 0.0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        def _call() -> LlmResponse:
            resp = self._client.post(
                self.API_URL,
                json=payload,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text_parts = [
                block["text"]
                for block in data.get("content", [])
                if block.get("type") == "text"
            ]
            return LlmResponse(content="".join(text_parts), model=self.model)

        return _retry_with_backoff(_call, max_retries=self._max_retries)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm_provider(settings=None) -> LlmProvider:
    """Instantiate the configured LLM provider from Settings.

    The factory is deliberately lightweight — it is called once at app startup
    and the resulting instance is stored on the FastAPI dependency graph.
    """
    if settings is None:
        from app.common.config import get_settings

        settings = get_settings()

    provider_name = getattr(settings, "llm_provider", "mock").lower()
    model = getattr(settings, "llm_model", "") or ""
    timeout = getattr(settings, "llm_timeout_seconds", 30)
    max_retries = getattr(settings, "llm_max_retries", 3)
    max_output = getattr(settings, "llm_max_output_tokens", 1024)

    if provider_name == "gemini":
        api_key = getattr(settings, "gemini_api_key", None)
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        if not model:
            raise RuntimeError("LLM_MODEL is required when LLM_PROVIDER=gemini (e.g. gemini-2.0-flash)")
        return GeminiLlmProvider(
            model=model,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            max_output_tokens=max_output,
        )

    if provider_name == "anthropic":
        api_key = getattr(settings, "anthropic_api_key", None)
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if not model:
            raise RuntimeError("LLM_MODEL is required when LLM_PROVIDER=anthropic (e.g. claude-sonnet-4-20250514)")
        return AnthropicLlmProvider(
            model=model,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            max_output_tokens=max_output,
        )

    # Default: deterministic mock (no API key needed, CI-safe)
    return MockLlmProvider(model_name=model or "mock-grounded-v1")
