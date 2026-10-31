"""Grounded RAG orchestration service coordinating retrieval, reranking, evidence, LLM synthesis, and citations."""

import logging
from typing import Optional

from app.contracts.rag_ask import RagAskRequest, RagAskResponse
from app.rag.citations import CitationExtractor
from app.rag.evidence import EvidenceBuilder
from app.rag.llm import LlmProvider, MockLlmProvider
from app.rag.reranker import DeterministicReranker
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

GENERIC_INSUFFICIENT_EVIDENCE_ANSWER = (
    "I do not have sufficient authorized documentation or evidence to answer this question."
)

SYSTEM_PROMPT = (
    "You are an enterprise knowledge assistant. Answer the user question strictly using ONLY "
    "the numbered evidence provided below. Every factual claim must cite its source index like [1] or [2]. "
    "If the evidence is insufficient, state that evidence is insufficient. Do not extrapolate or introduce external facts."
)


class GroundedRagService:
    """Orchestrates permission-aware Grounded RAG question answering."""

    def __init__(
        self,
        retriever: HybridRetriever,
        reranker: Optional[DeterministicReranker] = None,
        evidence_builder: Optional[EvidenceBuilder] = None,
        llm_provider: Optional[LlmProvider] = None,
        citation_extractor: Optional[CitationExtractor] = None,
    ):
        self.retriever = retriever
        self.reranker = reranker or DeterministicReranker(repository=getattr(retriever, "repository", None))
        self.evidence_builder = evidence_builder or EvidenceBuilder()
        self.llm_provider = llm_provider or MockLlmProvider()
        self.citation_extractor = citation_extractor or CitationExtractor()

    def ask(self, request: RagAskRequest) -> RagAskResponse:
        """Process a user question through Grounded RAG with permission isolation and citations.

        Pipeline stages:
        1. Query validation.
        2. Permission-filtered hybrid retrieval (pushdown ACL + source_types).
        3. Zero-candidate short-circuit to INSUFFICIENT_EVIDENCE.
        4. Deterministic reranking (text bonuses, candidate-grounded graph boost, diversity).
        5. Evidence context assembly (max 5 items, max 400 chars, no graph metadata).
        6. Mock LLM answer generation from evidence only.
        7. Citation extraction and mapping.
        8. Status and confidence resolution.
        """
        if not request.question or not request.question.strip():
            return RagAskResponse(
                question=request.question or "",
                answer=GENERIC_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                confidence="LOW",
                status="INSUFFICIENT_EVIDENCE",
            )

        cleaned_question = request.question.strip()
        logger.info(
            "grounded_rag_ask_initiated user_id=%s group_ids=%s query='%s' source_types=%s",
            request.user_id,
            request.group_ids,
            cleaned_question,
            request.source_types,
        )

        # 1. Permission-filtered hybrid retrieval (Step 11 security boundary)
        candidates = self.retriever.search(
            query=cleaned_question,
            limit=10,
            source_types=request.source_types,
            user_id=request.user_id,
            group_ids=request.group_ids,
        )

        # 2. Insufficient Evidence Rule: 0 authorized candidates -> INSUFFICIENT_EVIDENCE
        if not candidates:
            logger.info("grounded_rag_zero_candidates user_id=%s query='%s'", request.user_id, cleaned_question)
            return RagAskResponse(
                question=cleaned_question,
                answer=GENERIC_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                confidence="LOW",
                status="INSUFFICIENT_EVIDENCE",
            )

        # 3. Deterministic Reranker
        reranked_candidates = self.reranker.rerank(
            query=cleaned_question,
            candidates=candidates,
            source_types=request.source_types,
            user_id=request.user_id,
            group_ids=request.group_ids,
        )

        # 4. Evidence Builder
        context = self.evidence_builder.build(reranked_candidates)
        if not context.items:
            return RagAskResponse(
                question=cleaned_question,
                answer=GENERIC_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                confidence="LOW",
                status="INSUFFICIENT_EVIDENCE",
            )

        # 5. LLM Synthesis
        user_prompt = f"Question: {cleaned_question}\n\nNumbered Evidence:\n{context.formatted_context}\n\nAnswer:"
        llm_response = self.llm_provider.generate(SYSTEM_PROMPT, user_prompt)

        # 6. Citation Extraction & Mapping
        citations = self.citation_extractor.extract_citations(llm_response.content, context)

        # 7. Confidence & Status Handling
        # If no citations were generated or answer indicates insufficient evidence
        content_lower = llm_response.content.lower()
        if not citations or "insufficient" in content_lower or "not have sufficient" in content_lower:
            return RagAskResponse(
                question=cleaned_question,
                answer=GENERIC_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                confidence="LOW",
                status="INSUFFICIENT_EVIDENCE",
            )

        return RagAskResponse(
            question=cleaned_question,
            answer=llm_response.content,
            citations=citations,
            confidence="MEDIUM",
            status="ANSWERED",
        )
