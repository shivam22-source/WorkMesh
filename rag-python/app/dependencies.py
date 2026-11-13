"""Shared dependency providers for FastAPI application routes."""

from functools import lru_cache

from app.agent.service import AgentService
from app.common.config import get_settings
from app.indexing.repository import KnowledgeRepository, PostgresKnowledgeRepository
from app.rag.cross_encoder_reranker import CrossEncoderReranker
from app.rag.llm import get_llm_provider
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever


@lru_cache(maxsize=1)
def get_repository() -> KnowledgeRepository:
    settings = get_settings()
    return PostgresKnowledgeRepository(connection_url=settings.database_url)


@lru_cache(maxsize=1)
def get_hybrid_retriever() -> HybridRetriever:
    repo = get_repository()
    settings = get_settings()
    cross_encoder = (
        CrossEncoderReranker(
            model_name=settings.reranker_model,
            top_k=settings.reranker_top_k,
        )
        if settings.reranker == "cross_encoder"
        else None
    )
    return HybridRetriever(
        repository=repo,
        enable_query_routing=settings.enable_query_routing,
        cross_encoder_reranker=cross_encoder,
    )


@lru_cache(maxsize=1)
def get_grounded_rag_service() -> GroundedRagService:
    settings = get_settings()
    retriever = get_hybrid_retriever()
    llm_provider = get_llm_provider(settings)
    return GroundedRagService(retriever=retriever, llm_provider=llm_provider)


@lru_cache(maxsize=1)
def get_agent_service() -> AgentService:
    settings = get_settings()
    retriever = get_hybrid_retriever()
    repo = get_repository()
    llm_provider = get_llm_provider(settings)
    return AgentService(
        retriever=retriever,
        repository=repo,
        llm_provider=llm_provider,
    )
