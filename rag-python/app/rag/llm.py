"""LLM provider abstraction and deterministic mock provider for Grounded RAG."""

import re
from abc import ABC, abstractmethod
from typing import List

from pydantic import BaseModel


class LlmResponse(BaseModel):
    """Completion response from an LLM provider."""

    content: str
    model: str = "mock-grounded-v1"


class LlmProvider(ABC):
    """Abstract LLM completion provider."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> LlmResponse:
        """Generate answer completion strictly from supplied prompt context."""
        ...


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
        pattern = re.compile(r"\[(\d+)\]\s+Source:[^\n]+\nSnippet:\s*(.+?)(?=\n\n\[\d+\]|\Z)", re.DOTALL)
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
