"""Shared dependency providers for FastAPI application routes."""

from functools import lru_cache

from app.common.config import get_settings
from app.indexing.repository import KnowledgeRepository, PostgresKnowledgeRepository
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever


@lru_cache(maxsize=1)
def get_repository() -> KnowledgeRepository:
    settings = get_settings()
    return PostgresKnowledgeRepository(connection_url=settings.database_url)


@lru_cache(maxsize=1)
def get_hybrid_retriever() -> HybridRetriever:
    repo = get_repository()
    return HybridRetriever(repository=repo)


@lru_cache(maxsize=1)
def get_grounded_rag_service() -> GroundedRagService:
    retriever = get_hybrid_retriever()
    return GroundedRagService(retriever=retriever)
