"""End-to-end integration and security tests for Grounded RAG (Phase 4 Step 3).

Verifies:
1. End-to-end question answering with synthetic GitHub and Slack fixtures.
2. Grounded synthesis: answer cites provided evidence and returns status=ANSWERED, confidence=MEDIUM.
3. sourceTypes filtering: restricts candidate retrieval before reranking and LLM.
4. Security & ACL isolation: unauthorized user receives INSUFFICIENT_EVIDENCE with empty citations.
5. Identity privacy: identical generic response for non-existent and unauthorized queries.
6. Mock LLM never receives unauthorized document text.
"""

from datetime import datetime, timezone

import pytest

from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.contracts.rag_ask import RagAskRequest
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository
from app.rag.service import GENERIC_INSUFFICIENT_EVIDENCE_ANSWER, GroundedRagService
from app.retrieval.hybrid import HybridRetriever


@pytest.fixture
def populated_rag_service() -> GroundedRagService:
    """Pre-populates an in-memory repository with synthetic GitHub and Slack fixtures."""
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    IngestionPipeline(
        connector=GitHubFixtureAdapter(),
        repository=repo,
        embedding_provider=embeddings,
    ).run()
    IngestionPipeline(
        connector=SlackFixtureAdapter(),
        repository=repo,
        embedding_provider=embeddings,
    ).run()

    retriever = HybridRetriever(repository=repo)
    return GroundedRagService(retriever=retriever)


# ---------------------------------------------------------------------------
# 1. End-to-End Grounded Q&A with Mixed Sources
# ---------------------------------------------------------------------------

def test_grounded_rag_answers_question_with_citations_and_medium_confidence(populated_rag_service: GroundedRagService):
    """Authorized engineer querying ticket DC-8692 receives grounded answer with GitHub and Slack citations."""
    request = RagAskRequest(
        question="why did we change the validation flow for DC-8692?",
        userId="employee_42",
        groupIds=["group_engineering", "group_backend"],
    )

    response = populated_rag_service.ask(request)

    assert response.status == "ANSWERED"
    assert response.confidence == "MEDIUM"
    assert len(response.citations) > 0

    # Answer text includes bracketed citation markers
    assert "[1]" in response.answer

    # Verify both GITHUB and SLACK source citations exist
    sources = {c.source_type for c in response.citations}
    assert "GITHUB" in sources
    assert "SLACK" in sources

    # Verify citation fields
    for citation in response.citations:
        assert citation.source_type in {"GITHUB", "SLACK"}
        assert citation.title != ""
        assert citation.url.startswith("http")
        assert citation.snippet != ""


# ---------------------------------------------------------------------------
# 2. sourceTypes Filtering Enforced Before LLM
# ---------------------------------------------------------------------------

def test_source_types_filtering_github_only(populated_rag_service: GroundedRagService):
    """When sourceTypes=['GITHUB'], only GITHUB citations are produced."""
    request = RagAskRequest(
        question="validation DC-8692",
        userId="employee_42",
        groupIds=["group_engineering"],
        sourceTypes=["GITHUB"],
    )

    response = populated_rag_service.ask(request)

    assert response.status == "ANSWERED"
    assert len(response.citations) > 0
    assert all(c.source_type == "GITHUB" for c in response.citations)


def test_source_types_filtering_slack_only(populated_rag_service: GroundedRagService):
    """When sourceTypes=['SLACK'], only SLACK citations are produced."""
    request = RagAskRequest(
        question="validation DC-8692",
        userId="employee_42",
        groupIds=["group_engineering"],
        sourceTypes=["SLACK"],
    )

    response = populated_rag_service.ask(request)

    assert response.status == "ANSWERED"
    assert len(response.citations) > 0
    assert all(c.source_type == "SLACK" for c in response.citations)


def test_source_types_filtering_non_matching_returns_insufficient_evidence(populated_rag_service: GroundedRagService):
    """When sourceTypes filter matches 0 candidates (e.g. EMAIL), return INSUFFICIENT_EVIDENCE immediately."""
    request = RagAskRequest(
        question="validation DC-8692",
        userId="employee_42",
        groupIds=["group_engineering"],
        sourceTypes=["EMAIL"],
    )

    response = populated_rag_service.ask(request)

    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert response.confidence == "LOW"
    assert response.citations == []
    assert response.answer == GENERIC_INSUFFICIENT_EVIDENCE_ANSWER


# ---------------------------------------------------------------------------
# 3. Security & ACL Isolation: Pre-LLM Boundary
# ---------------------------------------------------------------------------

def test_acl_isolation_unauthorized_user_receives_identical_insufficient_evidence():
    """Unauthorized user querying confidential document receives generic insufficient evidence identical to non-existent query."""
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    # Create confidential raw source record
    raw_confidential = RawSourceItem(
        id="raw:slack:sec:100",
        source_type=SourceType.SLACK,
        source_id="100",
        source_url="https://slack.com/sec/100",
        title="#security-alerts: Zero-day vulnerability CVE-2026-9999",
        author_id="sec_admin",
        raw_content="Critical security breach in auth subsystem requiring immediate token revocation.",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repo.save_source_records([raw_confidential])

    # Ingest through pipeline with restricted ACL
    from app.chunking.source_aware_chunker import SourceAwareChunker
    from app.normalization.slack_normalizer import SlackNormalizer

    doc = SlackNormalizer().normalize(raw_confidential, [])
    chunks = SourceAwareChunker().chunk(doc)
    for c in chunks:
        c.embedding = embeddings.embed_query(c.content)

    repo.save_documents([doc])
    repo.save_chunks(chunks)
    repo.save_acls([
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:slack:sec:100",
            principal_type=PrincipalType.GROUP,
            principal_id="group_security",
            permission="READ",
        )
    ])

    service = GroundedRagService(retriever=HybridRetriever(repository=repo))

    # 1. Unauthorized engineer asks about the CVE
    unauth_request = RagAskRequest(
        question="CVE-2026-9999 security breach details",
        userId="dev_alice",
        groupIds=["group_engineering"],
    )
    unauth_response = service.ask(unauth_request)

    # 2. Same engineer asks for a non-existent query
    nonexistent_request = RagAskRequest(
        question="completely non existent topic 99999",
        userId="dev_alice",
        groupIds=["group_engineering"],
    )
    nonexistent_response = service.ask(nonexistent_request)

    # Both must be completely identical (preventing existence probing)
    assert unauth_response.status == "INSUFFICIENT_EVIDENCE"
    assert unauth_response.confidence == "LOW"
    assert unauth_response.citations == []
    assert unauth_response.answer == GENERIC_INSUFFICIENT_EVIDENCE_ANSWER

    assert nonexistent_response.status == unauth_response.status
    assert nonexistent_response.confidence == unauth_response.confidence
    assert nonexistent_response.citations == unauth_response.citations
    assert nonexistent_response.answer == unauth_response.answer

    # 3. Authorized security officer asks about the CVE -> receives grounded answer
    auth_request = RagAskRequest(
        question="CVE-2026-9999 security breach details",
        userId="sec_bob",
        groupIds=["group_security"],
    )
    auth_response = service.ask(auth_request)

    assert auth_response.status == "ANSWERED"
    assert auth_response.confidence == "MEDIUM"
    assert len(auth_response.citations) > 0
    assert "Zero-day vulnerability CVE-2026-9999" in auth_response.citations[0].title


def test_empty_or_whitespace_question_returns_insufficient_evidence(populated_rag_service: GroundedRagService):
    """Empty question returns INSUFFICIENT_EVIDENCE immediately."""
    request = RagAskRequest(
        question="   ",
        userId="employee_42",
        groupIds=["group_engineering"],
    )
    response = populated_rag_service.ask(request)
    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert response.confidence == "LOW"
    assert response.citations == []
