"""Unit tests for MockLlmProvider: grounding, deterministic extractive synthesis, and docstrings."""

from app.rag.llm import MockLlmProvider
from app.rag.service import SYSTEM_PROMPT


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
