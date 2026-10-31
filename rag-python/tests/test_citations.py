"""Unit tests for CitationExtractor: extraction, deduplication, and out-of-bounds safety."""

from app.rag.citations import CitationExtractor
from app.rag.evidence import EvidenceContext, EvidenceItem


def test_citation_extractor_resolves_bracketed_markers():
    """Extracts [1] and [2] and maps to CitationItem records with exact URL and metadata."""
    extractor = CitationExtractor()
    item1 = EvidenceItem(index=1, chunk_id="c1", document_id="d1", source_type="GITHUB", title="PR 101", source_url="https://github.com/101", content="Snippet 1", score=0.03)
    item2 = EvidenceItem(index=2, chunk_id="c2", document_id="d2", source_type="SLACK", title="Thread C01", source_url="https://slack.com/C01", content="Snippet 2", score=0.02)
    context = EvidenceContext(items=[item1, item2], formatted_context="")

    answer = "According to PR 101 [1], changes were verified. Discussion in Slack confirmed [2]."
    citations = extractor.extract_citations(answer, context)

    assert len(citations) == 2
    assert citations[0].source_type == "GITHUB"
    assert citations[0].title == "PR 101"
    assert citations[0].url == "https://github.com/101"
    assert citations[0].snippet == "Snippet 1"

    assert citations[1].source_type == "SLACK"
    assert citations[1].title == "Thread C01"
    assert citations[1].url == "https://slack.com/C01"
    assert citations[1].snippet == "Snippet 2"


def test_citation_extractor_deduplicates_repeated_markers_in_order_of_first_appearance():
    """Repeated occurrences of [1] produce a single CitationItem preserved at first appearance."""
    extractor = CitationExtractor()
    item1 = EvidenceItem(index=1, chunk_id="c1", document_id="d1", source_type="GITHUB", title="PR 101", source_url="https://github.com/101", content="Snippet 1", score=0.03)
    item2 = EvidenceItem(index=2, chunk_id="c2", document_id="d2", source_type="SLACK", title="Thread C01", source_url="https://slack.com/C01", content="Snippet 2", score=0.02)
    context = EvidenceContext(items=[item1, item2], formatted_context="")

    answer = "PR 101 stated this [1], then PR 101 confirmed that [1], and Slack agreed [2], with PR 101 again [1]."
    citations = extractor.extract_citations(answer, context)

    assert len(citations) == 2
    assert [c.title for c in citations] == ["PR 101", "Thread C01"]


def test_citation_extractor_safely_ignores_out_of_bounds_and_hallucinated_markers():
    """Markers referencing indices outside the supplied context (e.g. [99]) are safely dropped."""
    extractor = CitationExtractor()
    item1 = EvidenceItem(index=1, chunk_id="c1", document_id="d1", source_type="GITHUB", title="PR 101", source_url="https://github.com/101", content="Snippet 1", score=0.03)
    context = EvidenceContext(items=[item1], formatted_context="")

    answer = "Claim from PR [1], but also claim from [99] and [0]."
    citations = extractor.extract_citations(answer, context)

    assert len(citations) == 1
    assert citations[0].title == "PR 101"
