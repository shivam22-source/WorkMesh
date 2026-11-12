"""DTO validation tests for WorkMesh API request/response models.

Validates that:
- AskRequest rejects null/blank questions.
- AskResponse rejects null/blank answers, status, confidence.
- CitationItem rejects null/blank fields (sourceType, title, url, snippet).
- SearchRequest rejects null/blank queries.
"""

import pytest
from pydantic import ValidationError

from app.api.public_v1 import AskRequest, AskResponse, CitationItem, SearchRequest


def test_ask_request_rejects_blank_question():
    """AskRequest rejects blank question strings."""
    with pytest.raises(ValidationError):
        AskRequest(question="")

    with pytest.raises(ValidationError):
        AskRequest(question="   ")


def test_ask_request_rejects_none_question():
    """AskRequest rejects None question values."""
    with pytest.raises(ValidationError):
        AskRequest(question=None)  # type: ignore


def test_search_request_rejects_blank_query():
    """SearchRequest rejects blank query strings."""
    with pytest.raises(ValidationError):
        SearchRequest(query="")

    with pytest.raises(ValidationError):
        SearchRequest(query="   ")


def test_citation_item_requires_all_fields():
    """CitationItem requires sourceType, title, url, and snippet."""
    # Valid
    c = CitationItem(
        sourceType="GITHUB",
        title="Title",
        url="https://example.com",
        snippet="Snippet",
    )
    assert c.sourceType == "GITHUB"

    # Missing sourceType
    with pytest.raises(ValidationError):
        CitationItem(title="Title", url="https://example.com", snippet="Snippet")  # type: ignore

    # Missing title
    with pytest.raises(ValidationError):
        CitationItem(sourceType="GITHUB", url="https://example.com", snippet="Snippet")  # type: ignore

    # Missing url
    with pytest.raises(ValidationError):
        CitationItem(sourceType="GITHUB", title="Title", snippet="Snippet")  # type: ignore

    # Missing snippet
    with pytest.raises(ValidationError):
        CitationItem(sourceType="GITHUB", title="Title", url="https://example.com")  # type: ignore


def test_ask_response_validates_required_fields():
    """AskResponse requires answer, confidence, and status."""
    # Valid
    resp = AskResponse(
        question="Why did flow change?",
        answer="Flow changed due to DC-8692.",
        citations=[],
        confidence="HIGH",
        status="ANSWERED",
    )
    assert resp.status == "ANSWERED"

    # Missing answer
    with pytest.raises(ValidationError):
        AskResponse(
            question="Why did flow change?",
            citations=[],
            confidence="HIGH",
            status="ANSWERED",
        )  # type: ignore

    # Missing confidence
    with pytest.raises(ValidationError):
        AskResponse(
            question="Why did flow change?",
            answer="Flow changed.",
            citations=[],
            status="ANSWERED",
        )  # type: ignore

    # Missing status
    with pytest.raises(ValidationError):
        AskResponse(
            question="Why did flow change?",
            answer="Flow changed.",
            citations=[],
            confidence="HIGH",
        )  # type: ignore
