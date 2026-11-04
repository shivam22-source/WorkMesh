"""Port of Java SearchServiceImplTest DTO validation tests to pytest.

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
    """Java port: askRejectsBlankQuestion."""
    with pytest.raises(ValidationError):
        AskRequest(question="")

    with pytest.raises(ValidationError):
        AskRequest(question="   ")


def test_ask_request_rejects_none_question():
    """Java port: askRejectsNullQuestion."""
    with pytest.raises(ValidationError):
        AskRequest(question=None)  # type: ignore


def test_search_request_rejects_blank_query():
    """Java port: searchWithBlankQueryReturnsBadRequest."""
    with pytest.raises(ValidationError):
        SearchRequest(query="")

    with pytest.raises(ValidationError):
        SearchRequest(query="   ")


def test_citation_item_requires_all_fields():
    """Java port: askRejectsCitationWithNullOrBlankSourceType/Title/Url/Snippet."""
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
    """Java port: askRejectsNullAnswer/Confidence/Status."""
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
