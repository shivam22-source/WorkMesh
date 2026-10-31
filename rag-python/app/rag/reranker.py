"""Deterministic reranker with query alignment, candidate-grounded graph boosting, and diversity discounting."""

import logging
import re
from typing import Dict, List, Optional, Set

from app.contracts.rag_search import RagSearchResultItem
from app.indexing.repository import KnowledgeRepository
from app.normalization.common import extract_ticket_ids

logger = logging.getLogger(__name__)

# Standard PR reference pattern (e.g. PR #101, PR 101, #101, pull/101)
PR_NUMBER_PATTERN = re.compile(r"(?:PR\s*#?|pull/?|#)(\d{1,6})\b", re.IGNORECASE)

# Standard Git commit SHA prefix pattern (7 to 40 hexadecimal characters)
COMMIT_SHA_PATTERN = re.compile(r"\b([0-9a-fA-F]{7,40})\b")


def map_document_id_to_entity_id(document_id: str) -> Optional[str]:
    """Map verified canonical document_id to graph entity_id.

    Verified mappings from normalizers:
    - doc:github:{repo}:pr:{number} -> pr:{repo}:{number}
    - doc:github:{repo}:commit:{sha} -> commit:{repo}:{sha}
    - doc:slack:{channel_id}:thread:{thread_ts} -> slack:{channel_id}:{thread_ts}

    Returns None for any unmapped or unverified format, safely skipping graph boosting.
    """
    if not document_id:
        return None

    # 1. GitHub Pull Request
    m_pr = re.match(r"^doc:github:(.+):pr:(\d+)$", document_id)
    if m_pr:
        return f"pr:{m_pr.group(1)}:{m_pr.group(2)}"

    # 2. GitHub Commit
    m_commit = re.match(r"^doc:github:(.+):commit:([0-9a-fA-F]+)$", document_id)
    if m_commit:
        return f"commit:{m_commit.group(1)}:{m_commit.group(2)}"

    # 3. Slack Thread (note verified presence of :thread: in doc_id, omitted in entity_id)
    m_slack = re.match(r"^doc:slack:([^:]+):thread:(.+)$", document_id)
    if m_slack:
        return f"slack:{m_slack.group(1)}:{m_slack.group(2)}"

    return None


class DeterministicReranker:
    """Reranks retrieval candidate chunks using query alignment, authorized graph boosting, and diversity."""

    def __init__(self, repository: Optional[KnowledgeRepository] = None):
        self.repository = repository

    def rerank(
        self,
        query: str,
        candidates: List[RagSearchResultItem],
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Rerank candidate items deterministically.

        Guarantees:
        - Filters out candidates not matching source_types if provided.
        - Derives entity relationships strictly from candidate pool without unrestricted enumeration.
        - Applies bounded relationship boost (+0.0020 max) and text match bonus (+0.0010 max).
        - Applies deterministic diversity discounting (1.0, 0.80, 0.60) grouped by document_id.
        - Output ordering is invariant to candidate input order.
        """
        if not candidates or not query or not query.strip():
            return []

        # 1. Defensive source_types filter
        filtered_candidates = candidates
        if source_types:
            allowed = {st.upper() for st in source_types}
            filtered_candidates = [c for c in candidates if c.source_type.upper() in allowed]
            if not filtered_candidates:
                return []

        # 2. Resolve starting entities grounded in candidate pool
        authorized_neighbor_ids: Set[str] = set()
        if self.repository:
            starting_entity_ids = self._resolve_starting_entities(query, filtered_candidates)
            for eid in sorted(list(starting_entity_ids)):
                try:
                    rels = self.repository.get_relationships_for_entity(
                        entity_id=eid,
                        direction="BOTH",
                        user_id=user_id,
                        group_ids=group_ids,
                    )
                    for rel, neighbor in rels:
                        authorized_neighbor_ids.add(neighbor.id)
                except Exception as e:
                    logger.debug("reranker_relationship_lookup_skipped entity=%s err=%s", eid, e)

        # 3. Compute raw bonuses for each candidate
        cleaned_query = query.strip()
        query_lower = cleaned_query.lower()
        query_tokens = [t.lower() for t in re.findall(r"\b[\w-]+\b", cleaned_query) if len(t) > 1]

        candidate_data: List[Dict] = []
        for cand in filtered_candidates:
            text_bonus = self._compute_text_bonus(cand, query_lower, query_tokens)

            rel_boost = 0.0
            entity_id = map_document_id_to_entity_id(cand.document_id)
            if entity_id and entity_id in authorized_neighbor_ids:
                rel_boost = 0.0020

            candidate_data.append({
                "item": cand,
                "base_score": cand.score,
                "text_bonus": text_bonus,
                "rel_boost": rel_boost,
                "unweighted_score": cand.score + text_bonus + rel_boost,
            })

        # 4. Phase 1 Diversity Discounting: group by document_id and sort deterministically
        doc_groups: Dict[str, List[Dict]] = {}
        for entry in candidate_data:
            doc_groups.setdefault(entry["item"].document_id, []).append(entry)

        reranked_entries: List[Dict] = []
        # Sort document keys deterministically
        for doc_id in sorted(doc_groups.keys()):
            group = doc_groups[doc_id]
            # Intra-doc deterministic sort: base_rrf_score DESC, chunk_id ASC
            group.sort(key=lambda x: (-x["base_score"], x["item"].chunk_id))

            for rank_in_doc, entry in enumerate(group):
                if rank_in_doc == 0:
                    factor = 1.0
                elif rank_in_doc == 1:
                    factor = 0.80
                else:
                    factor = 0.60

                final_score = round(entry["unweighted_score"] * factor, 6)
                entry["final_score"] = final_score
                reranked_entries.append(entry)

        # 5. Phase 2 Global Deterministic Reranking Sort
        # Tie-breakers: final_score DESC, base_score DESC, chunk_id ASC
        reranked_entries.sort(key=lambda x: (-x["final_score"], -x["base_score"], x["item"].chunk_id))

        # 6. Reconstruct RagSearchResultItem records with updated reranked scores
        results: List[RagSearchResultItem] = []
        for entry in reranked_entries:
            item = entry["item"]
            results.append(
                RagSearchResultItem(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    source_type=item.source_type,
                    title=item.title,
                    snippet=item.snippet,
                    source_url=item.source_url,
                    author=item.author,
                    score=entry["final_score"],
                )
            )

        return results

    def _resolve_starting_entities(
        self,
        query: str,
        candidates: List[RagSearchResultItem],
    ) -> Set[str]:
        """Deterministically resolve starting graph entities from query grounded in candidates."""
        starting_ids: Set[str] = set()

        # 1. Ticket IDs are globally unique within domain
        for tid in extract_ticket_ids(query):
            starting_ids.add(f"ticket:{tid.upper()}")

        # Extract mapped candidate entities for candidate-grounded resolution
        candidate_entities: Set[str] = set()
        for c in candidates:
            eid = map_document_id_to_entity_id(c.document_id)
            if eid:
                candidate_entities.add(eid)

        # 2. PR numbers: ground strictly in candidates
        pr_matches = PR_NUMBER_PATTERN.findall(query)
        for pr_num in pr_matches:
            # Find candidate PR entities matching pr:*:{pr_num}
            matched_pr_entities = {
                eid for eid in candidate_entities
                if re.match(rf"^pr:[^:]+:{re.escape(pr_num)}$", eid)
            }
            if len(matched_pr_entities) == 1:
                starting_ids.add(next(iter(matched_pr_entities)))
            # If 0 or >1 (ambiguous across repos), skip relationship boost

        # 3. Commit SHAs: ground strictly in candidates (>= 7 hex characters)
        sha_matches = COMMIT_SHA_PATTERN.findall(query)
        for sha_prefix in sha_matches:
            prefix_lower = sha_prefix.lower()
            matched_commits = {
                eid for eid in candidate_entities
                if eid.startswith("commit:") and eid.split(":")[-1].lower().startswith(prefix_lower)
            }
            if len(matched_commits) == 1:
                starting_ids.add(next(iter(matched_commits)))
            # If 0 or >1 (ambiguous across repos), skip relationship boost

        return starting_ids

    def _compute_text_bonus(
        self,
        candidate: RagSearchResultItem,
        query_lower: str,
        query_tokens: List[str],
    ) -> float:
        """Compute bounded text match bonus (max +0.0010)."""
        bonus = 0.0
        title_lower = (candidate.title or "").lower()
        snippet_lower = (candidate.snippet or "").lower()

        if query_lower in title_lower:
            bonus += 0.0006
        if query_lower in snippet_lower:
            bonus += 0.0003

        if query_tokens:
            matches = sum(1 for t in query_tokens if t in title_lower or t in snippet_lower)
            coverage = matches / len(query_tokens)
            bonus += round(coverage * 0.0001, 6)

        return min(bonus, 0.0010)
