"""Unit tests for EvidenceBuilder: numbering, budgeting, truncation, and metadata containment."""

from app.contracts.rag_search import RagSearchResultItem
from app.rag.evidence import MAX_EVIDENCE_ITEMS, EvidenceBuilder


def test_evidence_builder_numbers_items_sequentially():
    """Evidence context assigns sequential stable indices 1..N."""
    builder = EvidenceBuilder()
    cands = [
        RagSearchResultItem(chunk_id=f"c{i}", document_id=f"doc:{i}", source_type="GITHUB", title=f"Title {i}", snippet=f"Snippet content {i}", source_url=f"https://github.com/{i}", score=0.03 - (i * 0.001))
        for i in range(1, 4)
    ]

    context = builder.build(cands)

    assert len(context.items) == 3
    assert [item.index for item in context.items] == [1, 2, 3]

    # Verify formatted context blocks
    assert "[1] Source: GITHUB | Title: Title 1 | URL: https://github.com/1" in context.formatted_context
    assert "[2] Source: GITHUB | Title: Title 2 | URL: https://github.com/2" in context.formatted_context
    assert "[3] Source: GITHUB | Title: Title 3 | URL: https://github.com/3" in context.formatted_context
    assert "Snippet: Snippet content 1" in context.formatted_context


def test_evidence_builder_caps_at_max_items():
    """Evidence context includes at most MAX_EVIDENCE_ITEMS (default: 5)."""
    builder = EvidenceBuilder(max_items=MAX_EVIDENCE_ITEMS)
    cands = [
        RagSearchResultItem(chunk_id=f"c{i}", document_id=f"doc:{i}", source_type="GITHUB", title=f"Title {i}", snippet=f"Snippet {i}", source_url=f"https://github.com/{i}", score=0.03)
        for i in range(10)
    ]

    context = builder.build(cands)

    assert len(context.items) == MAX_EVIDENCE_ITEMS
    assert context.items[-1].index == MAX_EVIDENCE_ITEMS


def test_evidence_builder_truncates_long_snippets_without_breaking_words():
    """Snippets exceeding budget are cleanly truncated at word boundaries with ellipsis."""
    builder = EvidenceBuilder(max_snippet_chars=50)
    long_snippet = "This is a comprehensive explanation of the authentication refactor that touches multiple modules."
    cand = RagSearchResultItem(chunk_id="c1", document_id="doc:1", source_type="GITHUB", title="Auth", snippet=long_snippet, source_url="https://url", score=0.03)

    context = builder.build([cand])

    assert len(context.items) == 1
    content = context.items[0].content
    assert len(content) <= 50
    assert content.endswith("...")
    # Does not break mid-word
    assert not content[:-3].endswith(" ")


def test_evidence_builder_never_includes_graph_metadata():
    """Evidence context contains only document chunks; graph edge names and entity types are strictly absent."""
    builder = EvidenceBuilder()
    cand = RagSearchResultItem(
        chunk_id="chunk_100",
        document_id="doc:github:repo:pr:101",
        source_type="GITHUB",
        title="Fix validation flow",
        snippet="Ticket DC-100 resolved with defensive checks.",
        source_url="https://github.com/repo/pull/101",
        score=0.032,
    )

    context = builder.build([cand])

    # No graph relationship types or entity prefixes in formatted text
    for forbidden in ["implemented_by", "discussed_in", "authored_by", "contains", "ticket:DC-100", "pr:repo:101"]:
        assert forbidden not in context.formatted_context


def test_evidence_builder_handles_empty_candidates():
    """Empty candidate list produces empty EvidenceContext."""
    builder = EvidenceBuilder()
    context = builder.build([])

    assert len(context.items) == 0
    assert context.formatted_context == ""
