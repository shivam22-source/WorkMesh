"""Hybrid retrieval component combining lexical and vector search via Reciprocal Rank Fusion (AD-02, AD-06).

Combines full-text lexical search and vector similarity retrieval into a unified,
deduplicated result list ranked by Reciprocal Rank Fusion (RRF).
"""

import logging
from typing import Dict, List, Optional

from app.contracts.rag_search import RagSearchResultItem
from app.indexing.repository import KnowledgeRepository
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.query_classifier import QueryClassifier
from app.retrieval.vector import VectorRetriever

logger = logging.getLogger(__name__)

# Standard RRF constant (Cormack et al.)
DEFAULT_RRF_K = 60


def compute_rrf_score(
    lexical_rank: Optional[int],
    vector_rank: Optional[int],
    k: int = DEFAULT_RRF_K,
) -> float:
    """Compute Reciprocal Rank Fusion score from 1-based ranks.

    Formula:
        RRF(d) = sum(1 / (k + rank_m(d))) for each retrieval method m in which d appears.
    If an item does not appear in a method's candidate list, that method contributes 0.0.
    """
    score = 0.0
    if lexical_rank is not None and lexical_rank > 0:
        score += 1.0 / (k + lexical_rank)
    if vector_rank is not None and vector_rank > 0:
        score += 1.0 / (k + vector_rank)
    return score


class HybridRetriever:
    """Executes hybrid retrieval by fusing lexical and vector results with RRF.

    Query Routing Behavior (AD-06):
    - IDENTIFIER queries: Exact ticket IDs, commit hashes, or PR references. Both lexical and
      vector retrievers run; exact lexical matches naturally achieve rank #1 in the lexical list,
      giving them dominant RRF scores.
    - KEYWORD queries: Discrete technical terms or symbols. Both retrievers run; lexical captures
      exact token occurrences and vector captures contextual similarity.
    - SEMANTIC queries: Natural language inquiries or explanations. Both retrievers run; vector
      captures semantic alignment and lexical captures term overlap.
    - MIXED queries: Identifiers combined with questions or descriptions. Both retrievers run;
      lexical captures exact identifiers and vector captures question semantics.
    Running both retrievers for all queries is the least-surprising, unified behavior while allowing
    RRF to mathematically rank candidates based on their multi-modal consensus.
    """

    def __init__(
        self,
        repository: Optional[KnowledgeRepository] = None,
        lexical_retriever: Optional[LexicalRetriever] = None,
        vector_retriever: Optional[VectorRetriever] = None,
        query_classifier: Optional[QueryClassifier] = None,
        k: int = DEFAULT_RRF_K,
        default_user_id: Optional[str] = None,
        default_group_ids: Optional[List[str]] = None,
    ):
        self.default_user_id = default_user_id
        self.default_group_ids = default_group_ids

        if lexical_retriever is not None and vector_retriever is not None:
            self.lexical_retriever = lexical_retriever
            self.vector_retriever = vector_retriever
        elif repository is not None:
            self.lexical_retriever = LexicalRetriever(
                repository,
                default_user_id=default_user_id,
                default_group_ids=default_group_ids,
            )
            self.vector_retriever = VectorRetriever(
                repository,
                default_user_id=default_user_id,
                default_group_ids=default_group_ids,
            )
        else:
            raise ValueError("Either repository or both (lexical_retriever, vector_retriever) must be provided.")

        self.query_classifier = query_classifier or QueryClassifier()
        self.k = k

    def search(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Execute hybrid search with reciprocal rank fusion and ACL enforcement.

        Args:
            query: User search query string.
            limit: Maximum number of fused results to return.
            source_types: Optional list of source systems to filter by (e.g. ['SLACK', 'GITHUB']).
            user_id: Optional authenticated employee ID for ACL evaluation.
            group_ids: Optional list of groups the employee belongs to for ACL evaluation.

        Returns:
            Deduplicated list of RagSearchResultItem records ranked by RRF score descending.
            Note: RagSearchResultItem.score represents the RRF score, not a raw similarity or lexical score.
        """
        if not query or not query.strip():
            return []

        effective_user_id = user_id if user_id is not None else self.default_user_id
        effective_group_ids = group_ids if group_ids is not None else self.default_group_ids

        cleaned_query = query.strip()
        classification = self.query_classifier.classify(cleaned_query)
        logger.debug(
            "hybrid_search_started query='%s' type=%s limit=%d source_types=%s user_id=%s groups=%s",
            cleaned_query,
            classification.query_type.value,
            limit,
            source_types,
            effective_user_id,
            effective_group_ids,
        )

        # Candidate pool size: retrieve a wider pool from each source to allow RRF overlap
        candidate_pool_limit = max(limit * 2, 20)

        # Execute both retrievers with pushdown metadata & ACL filtering
        lexical_candidates = self.lexical_retriever.search(
            query=cleaned_query,
            limit=candidate_pool_limit,
            source_types=source_types,
            user_id=effective_user_id,
            group_ids=effective_group_ids,
        )
        vector_candidates = self.vector_retriever.search(
            query=cleaned_query,
            limit=candidate_pool_limit,
            source_types=source_types,
            user_id=effective_user_id,
            group_ids=effective_group_ids,
        )

        # Fuse and deduplicate results
        fused = self._fuse_results(
            lexical_results=lexical_candidates,
            vector_results=vector_candidates,
            limit=limit,
        )

        # Apply safety metadata filter in case an underlying source did not filter
        if source_types:
            normalized_types = {st.upper() for st in source_types}
            fused = [item for item in fused if item.source_type.upper() in normalized_types]

        return fused

    def _fuse_results(
        self,
        lexical_results: List[RagSearchResultItem],
        vector_results: List[RagSearchResultItem],
        limit: int,
    ) -> List[RagSearchResultItem]:
        """Combine and deduplicate candidate lists using 1-based RRF."""
        if not lexical_results and not vector_results:
            return []

        candidates: Dict[str, Dict] = {}

        # 1. Index lexical candidates with 1-based rank
        for rank, item in enumerate(lexical_results, start=1):
            candidates[item.chunk_id] = {
                "item": item,
                "lexical_rank": rank,
                "vector_rank": None,
                "snippet": item.snippet,
            }

        # 2. Index vector candidates with 1-based rank
        for rank, item in enumerate(vector_results, start=1):
            if item.chunk_id in candidates:
                candidates[item.chunk_id]["vector_rank"] = rank
                # Preserve lexical snippet if present; otherwise take vector snippet
                if not candidates[item.chunk_id]["snippet"]:
                    candidates[item.chunk_id]["snippet"] = item.snippet
            else:
                candidates[item.chunk_id] = {
                    "item": item,
                    "lexical_rank": None,
                    "vector_rank": rank,
                    "snippet": item.snippet,
                }

        # 3. Compute raw unrounded RRF scores for ranking
        for cand in candidates.values():
            cand["rrf_score"] = compute_rrf_score(
                lexical_rank=cand["lexical_rank"],
                vector_rank=cand["vector_rank"],
                k=self.k,
            )

        # 4. Sort strictly by RRF score descending.
        # Apply tie-breakers only when RRF scores are equal:
        # - lexical rank ascending
        # - vector rank ascending
        # - chunk_id ascending (deterministic tie-breaker)
        sorted_candidates = sorted(
            candidates.values(),
            key=lambda c: (
                -c["rrf_score"],
                c["lexical_rank"] if c["lexical_rank"] is not None else 999999,
                c["vector_rank"] if c["vector_rank"] is not None else 999999,
                c["item"].chunk_id,
            ),
        )

        # 5. Format top candidates into RagSearchResultItem records
        fused_items: List[RagSearchResultItem] = []
        for cand in sorted_candidates[:limit]:
            base_item = cand["item"]
            fused_items.append(
                RagSearchResultItem(
                    chunk_id=base_item.chunk_id,
                    document_id=base_item.document_id,
                    source_type=base_item.source_type,
                    title=base_item.title,
                    snippet=cand["snippet"],
                    source_url=base_item.source_url,
                    author=base_item.author,
                    score=round(cand["rrf_score"], 6),
                )
            )

        return fused_items
