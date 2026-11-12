"""Unit tests for weighted RRF, query-type routing, and HNSW ef_search settings."""

import math
from unittest.mock import MagicMock

from app.common.config import Settings
from app.contracts.rag_search import RagSearchResultItem
from app.indexing.repository import PostgresKnowledgeRepository
from app.retrieval.hybrid import HybridRetriever, compute_rrf_score
from app.retrieval.lexical import LexicalRetriever
from app.retrieval.vector import VectorRetriever


def _item(cid: str, st: str = "GITHUB") -> RagSearchResultItem:
    return RagSearchResultItem(
        chunk_id=cid,
        document_id=f"doc:{cid}",
        source_type=st,
        title=f"Title {cid}",
        snippet=f"Snippet {cid}",
        source_url=f"https://example.com/{cid}",
        score=0.5,
    )


def test_weighted_rrf_score():
    assert math.isclose(
        compute_rrf_score(lexical_rank=1, vector_rank=None, k=60, lexical_weight=1.6, vector_weight=0.4),
        1.6 / 61.0,
    )
    assert math.isclose(
        compute_rrf_score(lexical_rank=None, vector_rank=1, k=60, lexical_weight=1.6, vector_weight=0.4),
        0.4 / 61.0,
    )


def test_query_routing_weights_identifier_vs_semantic():
    lex = MagicMock(spec=LexicalRetriever)
    vec = MagicMock(spec=VectorRetriever)
    lex.search.return_value = [_item("c_lex")]
    vec.search.return_value = [_item("c_vec")]

    retriever = HybridRetriever(lexical_retriever=lex, vector_retriever=vec, enable_query_routing=True)

    # Ticket ID & snake_case technical symbol favor lexical candidate
    res_ticket = retriever.search("DC-8692", limit=5)
    assert res_ticket[0].chunk_id == "c_lex"

    res_symbol = retriever.search("ERR_MTLS_HANDSHAKE_495", limit=5)
    assert res_symbol[0].chunk_id == "c_lex"

    # Natural-language question favors vector candidate
    res_sem = retriever.search("how do we prevent duplicate credit card charges when clients retry", limit=5)
    assert res_sem[0].chunk_id == "c_vec"


def test_settings_default_hnsw_ef_search_and_routing():
    s = Settings(auth_mode="dev")
    assert s.hnsw_ef_search == 200
    assert s.enable_query_routing is True

    repo = PostgresKnowledgeRepository("postgresql://u:p@localhost:5432/db", hnsw_ef_search=300)
    assert repo.hnsw_ef_search == 300
