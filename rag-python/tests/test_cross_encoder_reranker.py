"""Tests for optional CrossEncoderReranker stage and RERANKER feature flag."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.chunking.models import CanonicalChunk
from app.common.config import Settings
from app.connectors.common.models import AclReference, PrincipalType
from app.contracts.rag_search import RagSearchResultItem
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.repository import InMemoryKnowledgeRepository
from app.normalization.models import CanonicalDocument
from app.rag.cross_encoder_reranker import CrossEncoderReranker
from app.retrieval.hybrid import HybridRetriever


def _cand(cid: str, title: str, snippet: str, score: float = 0.5) -> RagSearchResultItem:
    return RagSearchResultItem(
        chunk_id=cid,
        document_id=f"doc:{cid}",
        source_type="GITHUB",
        title=title,
        snippet=snippet,
        source_url=f"https://example.com/{cid}",
        score=score,
    )


def test_reranker_setting_validation():
    s_default = Settings(auth_mode="dev")
    assert s_default.reranker == "off"

    s_enabled = Settings(auth_mode="dev", reranker=" CROSS_ENCODER ")
    assert s_enabled.reranker == "cross_encoder"

    with pytest.raises(ValueError, match="Invalid RERANKER"):
        Settings(auth_mode="dev", reranker="unknown_mode")


def test_cross_encoder_reranker_caps_top_50_and_resorts():
    mock_model = MagicMock()
    # Give item_5 higher relevance score than item_0
    mock_model.predict.side_effect = lambda pairs: [0.1 if i != 5 else 9.5 for i in range(len(pairs))]

    candidates = [_cand(f"c{i:02d}", f"Title {i}", f"Snippet {i}", score=1.0 - i * 0.01) for i in range(60)]
    reranker = CrossEncoderReranker(top_k=50, model=mock_model)

    reranked = reranker.rerank("rotation grace period", candidates, limit=5)

    called_pairs = mock_model.predict.call_args[0][0]
    assert len(called_pairs) == 50
    assert len(reranked) == 5
    assert reranked[0].chunk_id == "c05"
    assert reranked[0].score == 9.5


def test_cross_encoder_only_sees_acl_authorized_candidates():
    """Unauthorized chunks must be excluded in retrieval BEFORE CrossEncoder scoring."""
    repo = InMemoryKnowledgeRepository()
    emb = MockEmbeddingProvider()
    now = datetime.now(timezone.utc)

    docs = [
        CanonicalDocument(
            id="doc:public",
            source_record_id="src:pub",
            source_type="GITHUB",
            title="Public Token Rotation Guide",
            content="authorized content about rotation",
            url="https://example.com/pub",
            author="alice",
            created_at=now,
            updated_at=now,
        ),
        CanonicalDocument(
            id="doc:secret",
            source_record_id="src:sec",
            source_type="EMAIL",
            title="Executive Compensation Secret",
            content="CONFIDENTIAL_SECRET_PAYLOAD rotation",
            url="https://example.com/sec",
            author="ceo",
            created_at=now,
            updated_at=now,
        ),
    ]
    chunks = [
        CanonicalChunk(
            id="c:public:0",
            document_id="doc:public",
            chunk_index=0,
            token_count=4,
            content_hash="h1",
            content="authorized content about rotation",
            embedding=emb.embed_query("authorized content about rotation"),
            created_at=now,
        ),
        CanonicalChunk(
            id="c:secret:0",
            document_id="doc:secret",
            chunk_index=0,
            token_count=3,
            content_hash="h2",
            content="CONFIDENTIAL_SECRET_PAYLOAD rotation",
            embedding=emb.embed_query("CONFIDENTIAL_SECRET_PAYLOAD rotation"),
            created_at=now,
        ),
    ]
    acls = [
        AclReference(
            resource_type="DOCUMENT",
            resource_id="doc:public",
            principal_type=PrincipalType.GROUP,
            principal_id="group_engineering",
            permission="READ",
        ),
        AclReference(
            resource_type="DOCUMENT",
            resource_id="doc:secret",
            principal_type=PrincipalType.GROUP,
            principal_id="group_exec",
            permission="READ",
        ),
    ]
    repo.save_documents(docs)
    repo.save_chunks(chunks)
    repo.save_acls(acls)

    captured_pairs = []

    class RecordingCrossEncoder:
        def predict(self, pairs):
            captured_pairs.extend(pairs)
            return [0.8 for _ in pairs]

    retriever = HybridRetriever(
        repository=repo,
        embedding_provider=emb,
        cross_encoder_reranker=CrossEncoderReranker(top_k=50, model=RecordingCrossEncoder()),
    )
    results = retriever.search("rotation", limit=10, user_id="eng_user", group_ids=["group_engineering"])

    assert [r.chunk_id for r in results] == ["c:public:0"]
    assert all("CONFIDENTIAL_SECRET_PAYLOAD" not in passage for _, passage in captured_pairs)
    assert retriever.last_stage_timings["rerankMs"] >= 0.0
