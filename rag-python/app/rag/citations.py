"""Citation extractor and metadata mapper parsing answer text against EvidenceContext."""

import re
from typing import Dict, List, Set

from app.contracts.rag_ask import CitationItem
from app.rag.evidence import EvidenceContext, EvidenceItem


class CitationExtractor:
    """Extracts inline citation markers [i] from answer text and maps to CitationItem records."""

    CITATION_PATTERN = re.compile(r"\[(\d+)\]")

    def extract_citations(
        self,
        answer_text: str,
        context: EvidenceContext,
    ) -> List[CitationItem]:
        """Parse all [i] markers and resolve to deduplicated CitationItem records.

        Invariants:
        - Resolves 1-based index i strictly against context.items.
        - Drops out-of-bounds indices (e.g. [99]) safely without error.
        - Preserves order of first appearance in the answer text.
        - Deduplicates repeated references to the same evidence index.
        """
        if not answer_text or not context or not context.items:
            return []

        # Build index lookup map: 1-based index -> EvidenceItem
        evidence_by_index: Dict[int, EvidenceItem] = {
            item.index: item for item in context.items
        }

        seen_indices: Set[int] = set()
        citations: List[CitationItem] = []

        for match in self.CITATION_PATTERN.finditer(answer_text):
            idx = int(match.group(1))
            if idx in seen_indices:
                continue

            item = evidence_by_index.get(idx)
            if item is None:
                # Out-of-bounds or hallucinated marker -> ignore safely
                continue

            seen_indices.add(idx)
            citations.append(
                CitationItem(
                    source_type=item.source_type,
                    title=item.title,
                    url=item.source_url,
                    snippet=item.content,
                )
            )

        return citations
