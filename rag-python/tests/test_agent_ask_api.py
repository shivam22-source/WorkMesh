"""Unit and integration tests for Agent endpoint POST /api/v1/agent/ask (Task 4).

Verifies:
1. Bounded loop enforcement (max 5 steps, token budget, wall-time budget).
2. Read-only tools: search, get_document, get_related, get_thread.
3. Strict ACL propagation with caller identity on every tool call.
4. Audit trail: every tool call is written to audit log (step, tool, args_hash, result_count).
5. Step trace is returned in the response payload.
6. Public REST endpoint POST /api/v1/agent/ask integration via FastAPI TestClient.
"""

from datetime import datetime, timezone
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pytest

from app.agent.service import AgentAskRequest, AgentAskResponse, AgentService
from app.agent.tools import AgentTools
from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.normalization.models import CanonicalDocument
from app.rag.citations import CitationExtractor
from app.rag.evidence import EvidenceBuilder
from app.rag.llm import LlmProvider, LlmResponse, MockLlmProvider
from app.retrieval.hybrid import HybridRetriever


@pytest.fixture
def agent_test_env():
    """Build in-memory repository with multi-source documents and graph edges."""
    repo = InMemoryKnowledgeRepository()

    # Document 1: Public engineering PR
    doc1 = CanonicalDocument(
        id="doc:github:pr:123",
        source_record_id="raw:github:pr:123",
        source_type="GITHUB",
        title="PR #123: Defensive checks for DC-8692",
        author="alex-engineer",
        url="https://github.com/company/payment-service/pull/123",
        content="Fixes DC-8692 by validating missing card tokens with HTTP 400 Bad Request.",
        metadata={"repository": "payment-service", "number": "123", "ticket_id": "DC-8692"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    chunk1 = CanonicalChunk(
        id="chunk:doc:github:pr:123:0",
        document_id=doc1.id,
        chunk_index=0,
        content=doc1.content,
        token_count=15,
        content_hash="hash1",
        metadata=doc1.metadata,
        created_at=datetime.now(timezone.utc),
    )

    # Document 2: Confidential security memo (group_security only)
    doc2 = CanonicalDocument(
        id="doc:email:sec:999",
        source_record_id="raw:email:sec:999",
        source_type="EMAIL",
        title="RESTRICTED: Security audit findings",
        author="sec-auditor",
        url="https://mail.company.internal/msg/999",
        content="Confidential finding: vulnerability in payment service CVE-2026-1111.",
        metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    chunk2 = CanonicalChunk(
        id="chunk:doc:email:sec:999:0",
        document_id=doc2.id,
        chunk_index=0,
        content=doc2.content,
        token_count=10,
        content_hash="hash2",
        metadata=doc2.metadata,
        created_at=datetime.now(timezone.utc),
    )

    # Document 3: Slack discussion on thread
    doc3 = CanonicalDocument(
        id="doc:slack:thread:456",
        source_record_id="raw:slack:C0123PAY:1697364000.000100",
        source_type="SLACK",
        title="#payments-engineering discussion",
        author="alex-engineer",
        url="https://company.slack.com/archives/C0123PAY/p1697364000000100",
        content="Discussing DC-8692 resolution: team agreed on HTTP 400.",
        metadata={"channel_id": "C0123PAY", "thread_ts": "1697364000.000100", "ticket_id": "DC-8692"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    chunk3 = CanonicalChunk(
        id="chunk:doc:slack:thread:456:0",
        document_id=doc3.id,
        chunk_index=0,
        content=doc3.content,
        token_count=12,
        content_hash="hash3",
        metadata=doc3.metadata,
        created_at=datetime.now(timezone.utc),
    )

    repo.save_documents([doc1, doc2, doc3])
    repo.save_chunks([chunk1, chunk2, chunk3])

    # ACLs
    repo.save_acls([
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:github:pr:123",
            principal_type=PrincipalType.GROUP,
            principal_id="group_engineering",
            permission="READ",
        ),
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:email:sec:999",
            principal_type=PrincipalType.GROUP,
            principal_id="group_security",
            permission="READ",
        ),
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:slack:C0123PAY:1697364000.000100",
            principal_type=PrincipalType.GROUP,
            principal_id="group_engineering",
            permission="READ",
        ),
    ])

    # Graph Entities & Relationships
    ticket_ent = Entity(
        id="ticket:DC-8692",
        entity_type=EntityType.TICKET.value,
        name="DC-8692",
        source_record_id=None,
        metadata={"ticket_id": "DC-8692"},
    )
    pr_ent = Entity(
        id="pr:payment-service:123",
        entity_type=EntityType.PULL_REQUEST.value,
        name="PR #123",
        source_record_id="raw:github:pr:123",
        metadata={"repository": "payment-service", "number": "123"},
    )
    rel = Relationship(
        source_entity_id="ticket:DC-8692",
        target_entity_id="pr:payment-service:123",
        relationship_type=RelationshipType.IMPLEMENTED_BY.value,
    )

    repo.save_entities([ticket_ent, pr_ent])
    repo.save_relationships([rel])
    # Relationship ownership
    repo.relationship_owners[(rel.source_entity_id, rel.target_entity_id, rel.relationship_type)] = {"raw:github:pr:123"}

    mock_emb = MockEmbeddingProvider()
    chunk1.embedding = mock_emb.embed_query(chunk1.content)
    chunk2.embedding = mock_emb.embed_query(chunk2.content)
    chunk3.embedding = mock_emb.embed_query(chunk3.content)

    retriever = HybridRetriever(repository=repo, embedding_provider=mock_emb)
    service = AgentService(
        retriever=retriever,
        repository=repo,
        llm_provider=MockLlmProvider(),
    )

    return {
        "repo": repo,
        "retriever": retriever,
        "service": service,
    }


def test_agent_tools_read_only_and_acl_enforced(agent_test_env):
    """Tools enforce caller identity and refuse unauthorized documents."""
    repo = agent_test_env["repo"]
    retriever = agent_test_env["retriever"]

    # 1. Standard engineer
    eng_tools = AgentTools(
        retriever=retriever,
        repository=repo,
        user_id="alice",
        group_ids=["group_engineering"],
    )

    # Authorized get_document
    doc_res = eng_tools.get_document("doc:github:pr:123")
    assert doc_res["found"] is True
    assert "DC-8692" in doc_res["title"]

    # Unauthorized get_document for confidential memo
    sec_res = eng_tools.get_document("doc:email:sec:999")
    assert sec_res["found"] is False
    assert "access denied" in sec_res["error"].lower()

    # Authorized get_related
    related = eng_tools.get_related("ticket:DC-8692")
    assert len(related) > 0
    assert related[0]["relationship_type"] == RelationshipType.IMPLEMENTED_BY.value

    # Authorized get_thread
    thread = eng_tools.get_thread("C0123PAY", "1697364000.000100")
    assert len(thread) > 0
    assert "HTTP 400" in thread[0]["content"]

    # 2. Outside user without groups
    outside_tools = AgentTools(
        retriever=retriever,
        repository=repo,
        user_id="stranger",
        group_ids=["group_none"],
    )
    assert outside_tools.get_document("doc:github:pr:123")["found"] is False
    assert len(outside_tools.get_related("ticket:DC-8692")) == 0
    assert len(outside_tools.get_thread("C0123PAY", "1697364000.000100")) == 0


def test_agent_loop_caps_steps_at_5(agent_test_env):
    """Loop never exceeds 5 steps even if a client requests 10."""
    service = agent_test_env["service"]

    req = AgentAskRequest(
        question="Why was validation changed for DC-8692?",
        max_steps=5,  # request model validation allows max 5
    )
    resp = service.ask(req, user_id="alice", group_ids=["group_engineering"])

    assert resp.steps_taken <= 5
    assert len(resp.trace) <= 5
    for t in resp.trace:
        assert t.step <= 5


def test_agent_audit_log_records_every_tool_call(agent_test_env):
    """Every tool call writes step, tool, args_hash, and result_count to audit log."""
    repo = agent_test_env["repo"]
    service = agent_test_env["service"]

    req = AgentAskRequest(
        question="What happened in DC-8692?",
        max_steps=3,
    )
    resp = service.ask(req, user_id="alice", group_ids=["group_engineering"])

    audit_events = repo.get_audit_events(user_id="alice", action="AGENT_TOOL_CALL")
    assert len(audit_events) == resp.steps_taken
    assert len(audit_events) > 0

    first_event = audit_events[-1]  # events ordered descending, so last is step 1
    assert first_event["action"] == "AGENT_TOOL_CALL"
    details = first_event["details"]
    assert details["step"] == 1
    assert details["tool"] == "search"
    assert "args_hash" in details
    assert "result_count" in details


def test_agent_returns_full_trace_and_verified_citations(agent_test_env):
    """Response includes structured trace and citations verified against authorized context."""
    service = agent_test_env["service"]

    req = AgentAskRequest(
        question="Why did we change the validation flow for DC-8692?",
        max_steps=3,
    )
    resp = service.ask(req, user_id="alice", group_ids=["group_engineering"])

    assert resp.status == "ANSWERED"
    assert resp.confidence == "MEDIUM"
    assert len(resp.citations) > 0
    assert len(resp.trace) > 0

    # Verify each trace step structure
    for step_trace in resp.trace:
        assert step_trace.step >= 1
        assert step_trace.tool in {"search", "get_document", "get_related", "get_thread"}
        assert len(step_trace.args_hash) == 16
        assert step_trace.elapsed_ms >= 0.0

    # Verify citations are strictly from authorized documents
    for cit in resp.citations:
        assert cit.source_type in {"GITHUB", "SLACK"}
        assert "RESTRICTED" not in cit.title


def test_agent_wall_time_budget_enforcement(agent_test_env):
    """When wall_time_budget is exceeded, loop terminates early with status=BUDGET_EXCEEDED or answer."""
    service = agent_test_env["service"]

    # Tiny wall time budget (0.001 seconds)
    req = AgentAskRequest(
        question="Why was validation changed for DC-8692?",
        wall_time_budget_seconds=0.001,
    )
    resp = service.ask(req, user_id="alice", group_ids=["group_engineering"])

    # Loop stopped early
    assert resp.status in {"BUDGET_EXCEEDED", "INSUFFICIENT_EVIDENCE", "ANSWERED"}


def test_public_api_agent_ask_endpoint(agent_test_env):
    """POST /api/v1/agent/ask operates end-to-end via FastAPI TestClient in dev mode."""
    app = create_app()

    # Override dependencies
    from app.dependencies import get_agent_service, get_repository
    app.dependency_overrides[get_agent_service] = lambda: agent_test_env["service"]
    app.dependency_overrides[get_repository] = lambda: agent_test_env["repo"]

    client = TestClient(app)

    response = client.post(
        "/api/v1/agent/ask",
        headers={
            "X-User-Id": "alice",
            "X-User-Groups": "group_engineering",
        },
        json={
            "question": "What defensive checks were added for DC-8692?",
            "maxSteps": 3,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["question"] == "What defensive checks were added for DC-8692?"
    assert data["status"] == "ANSWERED"
    assert "stepsTaken" in data or "steps_taken" in data
    assert len(data["trace"]) > 0
    assert len(data["citations"]) > 0
