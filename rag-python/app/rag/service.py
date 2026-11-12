"""Grounded RAG orchestration service coordinating retrieval, reranking, evidence, LLM synthesis, and citations."""

import logging
import time
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
        4. Deterministic reranking (text bonuses, [EXPERIMENTAL] candidate-grounded graph boost, diversity).
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
                latency_breakdown_ms={
                    "retrieval_ms": 0.0,
                    "rerank_ms": 0.0,
                    "evidence_ms": 0.0,
                    "llm_ms": 0.0,
                    "total_ms": 0.0,
                },
            )

        t_start = time.perf_counter()
        cleaned_question = request.question.strip()
        logger.info(
            "grounded_rag_ask_initiated user_id=%s group_ids=%s query='%s' source_types=%s",
            request.user_id,
            request.group_ids,
            cleaned_question,
            request.source_types,
        )

        # 1. Permission-filtered hybrid retrieval (Step 11 security boundary)
        t_retrieval_start = time.perf_counter()
        candidates = self.retriever.search(
            query=cleaned_question,
            limit=10,
            source_types=request.source_types,
            user_id=request.user_id,
            group_ids=request.group_ids,
        )
        retrieval_ms = round((time.perf_counter() - t_retrieval_start) * 1000, 2)

        # 2. Insufficient Evidence Rule: 0 authorized candidates -> INSUFFICIENT_EVIDENCE
        if not candidates:
            total_ms = round((time.perf_counter() - t_start) * 1000, 2)
            breakdown = {
                "retrieval_ms": retrieval_ms,
                "rerank_ms": 0.0,
                "evidence_ms": 0.0,
                "llm_ms": 0.0,
                "total_ms": total_ms,
            }
            logger.info(
                "grounded_rag_ask_completed user_id=%s status=INSUFFICIENT_EVIDENCE total_ms=%.2f breakdown=%s",
                request.user_id,
                total_ms,
                breakdown,
            )
            return RagAskResponse(
                question=cleaned_question,
                answer=GENERIC_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                confidence="LOW",
                status="INSUFFICIENT_EVIDENCE",
                latency_breakdown_ms=breakdown,
            )

        # 3. Deterministic Reranker
        t_rerank_start = time.perf_counter()
        reranked_candidates = self.reranker.rerank(
            query=cleaned_question,
            candidates=candidates,
            source_types=request.source_types,
            user_id=request.user_id,
            group_ids=request.group_ids,
        )
        rerank_ms = round((time.perf_counter() - t_rerank_start) * 1000, 2)

        # 4. Evidence Builder
        t_evidence_start = time.perf_counter()
        context = self.evidence_builder.build(reranked_candidates)
        evidence_ms = round((time.perf_counter() - t_evidence_start) * 1000, 2)
        if not context.items:
            total_ms = round((time.perf_counter() - t_start) * 1000, 2)
            breakdown = {
                "retrieval_ms": retrieval_ms,
                "rerank_ms": rerank_ms,
                "evidence_ms": evidence_ms,
                "llm_ms": 0.0,
                "total_ms": total_ms,
            }
            logger.info(
                "grounded_rag_ask_completed user_id=%s status=INSUFFICIENT_EVIDENCE total_ms=%.2f breakdown=%s",
                request.user_id,
                total_ms,
                breakdown,
            )
            return RagAskResponse(
                question=cleaned_question,
                answer=GENERIC_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                confidence="LOW",
                status="INSUFFICIENT_EVIDENCE",
                latency_breakdown_ms=breakdown,
            )

        # 5. LLM Synthesis
        t_llm_start = time.perf_counter()
        user_prompt = f"Question: {cleaned_question}\n\nNumbered Evidence:\n{context.formatted_context}\n\nAnswer:"
        llm_response = self.llm_provider.generate(SYSTEM_PROMPT, user_prompt)

        # 6. Citation Extraction & Mapping
        citations = self.citation_extractor.extract_citations(llm_response.content, context)
        llm_ms = round((time.perf_counter() - t_llm_start) * 1000, 2)

        total_ms = round((time.perf_counter() - t_start) * 1000, 2)
        breakdown = {
            "retrieval_ms": retrieval_ms,
            "rerank_ms": rerank_ms,
            "evidence_ms": evidence_ms,
            "llm_ms": llm_ms,
            "total_ms": total_ms,
        }

        # 7. Confidence & Status Handling
        # If no citations were generated or answer indicates insufficient evidence
        content_lower = llm_response.content.lower()
        if not citations or "insufficient" in content_lower or "not have sufficient" in content_lower:
            logger.info(
                "grounded_rag_ask_completed user_id=%s status=INSUFFICIENT_EVIDENCE total_ms=%.2f breakdown=%s",
                request.user_id,
                total_ms,
                breakdown,
            )
            return RagAskResponse(
                question=cleaned_question,
                answer=GENERIC_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                confidence="LOW",
                status="INSUFFICIENT_EVIDENCE",
                latency_breakdown_ms=breakdown,
            )

        logger.info(
            "grounded_rag_ask_completed user_id=%s status=ANSWERED total_ms=%.2f citations=%d breakdown=%s",
            request.user_id,
            total_ms,
            len(citations),
            breakdown,
        )
        return RagAskResponse(
            question=cleaned_question,
            answer=llm_response.content,
            citations=citations,
            confidence="MEDIUM",
            status="ANSWERED",
            latency_breakdown_ms=breakdown,
        )
