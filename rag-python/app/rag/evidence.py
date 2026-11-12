"""Evidence builder formatting authorized candidate chunks into numbered context blocks for LLM synthesis."""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.contracts.rag_search import RagSearchResultItem

MAX_EVIDENCE_ITEMS = 5
MAX_SNIPPET_CHARS = 400


class EvidenceItem(BaseModel):
    """An individual authorized piece of evidence with stable 1-based index."""

    index: int
    chunk_id: str
    document_id: str
    source_type: str
    title: str
    source_url: str
    author: Optional[str] = None
    content: str
    score: float


class EvidenceContext(BaseModel):
    """Structured evidence context ready for grounded LLM prompt assembly."""

    items: List[EvidenceItem] = Field(default_factory=list)
    formatted_context: str = ""


class EvidenceBuilder:
    """Builds numbered evidence context strictly from authorized retrieval candidates."""

    def __init__(
        self,
        max_items: int = MAX_EVIDENCE_ITEMS,
        max_snippet_chars: int = MAX_SNIPPET_CHARS,
    ):
        self.max_items = max_items
        self.max_snippet_chars = max_snippet_chars

    def build(self, candidates: List[RagSearchResultItem]) -> EvidenceContext:
        """Construct EvidenceContext from reranked candidate chunks.

        Invariants:
        - Contains at most max_items authorized chunks.
        - Snippets are cleanly truncated within max_snippet_chars.
        - Graph metadata and relationship edge names are strictly excluded.
        - Assigns stable 1-based sequential indices (1..N).
        """
        if not candidates:
            return EvidenceContext(items=[], formatted_context="")

        selected_candidates = candidates[: self.max_items]
        items: List[EvidenceItem] = []
        formatted_blocks: List[str] = []

        for idx, cand in enumerate(selected_candidates, start=1):
            clean_snippet = self._truncate_snippet(cand.snippet, self.max_snippet_chars)
            item = EvidenceItem(
                index=idx,
                chunk_id=cand.chunk_id,
                document_id=cand.document_id,
                source_type=cand.source_type,
                title=cand.title or "Untitled",
                source_url=cand.source_url or "",
                author=cand.author,
                content=clean_snippet,
                score=cand.score,
            )
            items.append(item)

            block = (
                f"[{item.index}] Source: {item.source_type} | Title: {item.title} | URL: {item.source_url}\n"
                f"Snippet: {item.content}"
            )
            formatted_blocks.append(block)

        formatted_context = "\n\n".join(formatted_blocks)
        return EvidenceContext(items=items, formatted_context=formatted_context)

    def _truncate_snippet(self, text: str, max_chars: int) -> str:
        """Truncate text to character budget without splitting mid-word."""
        if not text:
            return ""
        clean = " ".join(text.split()).strip()
        if len(clean) <= max_chars:
            return clean

        truncated = clean[: max_chars - 3]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]

        return truncated + "..."
