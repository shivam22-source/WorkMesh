"""End-to-end multi-tenant permission isolation and access control verification."""

from fastapi.testclient import TestClient

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, PrincipalType
from app.dependencies import get_grounded_rag_service, get_hybrid_retriever, get_repository
from app.normalization.models import CanonicalDocument
from app.indexing.repository import InMemoryKnowledgeRepository
from app.main import create_app
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever


def test_end_to_end_cross_tenant_permission_isolation():
    repo = InMemoryKnowledgeRepository()

    # 1. Seed Engineering Document
    doc_eng = CanonicalDocument(
        id="doc:eng:1",
        source_record_id="rec:eng:1",
        source_type="GITHUB",
        title="Engineering Architecture Secrets",
        content="Internal engineering Kubernetes cluster credentials and deployment keys.",
        author="eng_lead",
        url="https://github.com/company/repo/pull/100",
    )
    chunk_eng = CanonicalChunk(
        id="chunk:eng:1",
        document_id="doc:eng:1",
        chunk_index=0,
        content="Internal engineering Kubernetes cluster credentials and deployment keys.",
        content_hash="hash_eng_1",
        token_count=12,
        embedding=[0.1] * 1536,
        metadata={"source_type": "GITHUB", "title": doc_eng.title, "url": doc_eng.url},
    )
    acl_eng = AclReference(
        resource_type="DOCUMENT",
        resource_id="doc:eng:1",
        principal_type=PrincipalType.GROUP,
        principal_id="group_engineering",
    )

    # 2. Seed Finance Document
    doc_fin = CanonicalDocument(
        id="doc:fin:1",
        source_record_id="rec:fin:1",
        source_type="EMAIL",
        title="Executive Compensation and Payroll Q4",
        content="Confidential executive compensation bonus packages for executive directors.",
        author="cfo",
        url="https://mail.company.internal/thread/200",
    )
    chunk_fin = CanonicalChunk(
        id="chunk:fin:1",
        document_id="doc:fin:1",
        chunk_index=0,
        content="Confidential executive compensation bonus packages for executive directors.",
        content_hash="hash_fin_1",
        token_count=10,
        embedding=[0.2] * 1536,
        metadata={"source_type": "EMAIL", "title": doc_fin.title, "url": doc_fin.url},
    )
    acl_fin = AclReference(
        resource_type="DOCUMENT",
        resource_id="doc:fin:1",
        principal_type=PrincipalType.GROUP,
        principal_id="group_finance",
    )

    repo.save_documents([doc_eng, doc_fin])
    repo.save_chunks([chunk_eng, chunk_fin])
    repo.save_acls([acl_eng, acl_fin])

    retriever = HybridRetriever(repository=repo)
    rag_service = GroundedRagService(retriever=retriever)

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_hybrid_retriever] = lambda: retriever
    app.dependency_overrides[get_grounded_rag_service] = lambda: rag_service
    client = TestClient(app)

    # -----------------------------------------------------------------------
    # Case A: Engineer attempts to access Finance data
    # -----------------------------------------------------------------------
    res_eng_search = client.post(
        "/api/v1/search",
        json={"query": "compensation executive bonus"},
        headers={"X-User-Id": "alice_eng", "X-User-Groups": "group_engineering"},
    )
    assert res_eng_search.status_code == 200
    # Zero finance documents leaked to engineering user
    assert not any(item["documentId"] == "doc:fin:1" for item in res_eng_search.json()["results"])

    res_eng_filtered_search = client.post(
        "/api/v1/search",
        json={"query": "compensation executive bonus", "sourceTypes": ["EMAIL"]},
        headers={"X-User-Id": "alice_eng", "X-User-Groups": "group_engineering"},
    )
    assert res_eng_filtered_search.status_code == 200
    assert res_eng_filtered_search.json()["totalResults"] == 0

    # RAG ask scoped to EMAIL returns INSUFFICIENT_EVIDENCE
    res_eng_ask = client.post(
        "/api/v1/ask",
        json={"question": "What are executive compensation bonus packages?", "sourceTypes": ["EMAIL"]},
        headers={"X-User-Id": "alice_eng", "X-User-Groups": "group_engineering"},
    )
    assert res_eng_ask.status_code == 200
    data_eng_ask = res_eng_ask.json()
    assert data_eng_ask["status"] == "INSUFFICIENT_EVIDENCE"
    assert len(data_eng_ask["citations"]) == 0

    # -----------------------------------------------------------------------
    # Case B: Engineer accesses authorized Engineering data
    # -----------------------------------------------------------------------
    res_eng_search_ok = client.post(
        "/api/v1/search",
        json={"query": "Kubernetes cluster credentials"},
        headers={"X-User-Id": "alice_eng", "X-User-Groups": "group_engineering"},
    )
    assert res_eng_search_ok.status_code == 200
    assert res_eng_search_ok.json()["totalResults"] >= 1
    assert any(item["chunkId"] == "chunk:eng:1" for item in res_eng_search_ok.json()["results"])

    # -----------------------------------------------------------------------
    # Case C: Finance user accesses authorized Finance data
    # -----------------------------------------------------------------------
    res_fin_search = client.post(
        "/api/v1/search",
        json={"query": "compensation executive bonus"},
        headers={"X-User-Id": "bob_fin", "X-User-Groups": "group_finance"},
    )
    assert res_fin_search.status_code == 200
    assert res_fin_search.json()["totalResults"] >= 1
    assert any(item["documentId"] == "doc:fin:1" for item in res_fin_search.json()["results"])
    # Zero engineering data leaked to finance user
    assert not any(item["documentId"] == "doc:eng:1" for item in res_fin_search.json()["results"])

    # Finance user asks question about compensation -> answered with citations
    res_fin_ask = client.post(
        "/api/v1/ask",
        json={"question": "What are executive compensation bonus packages?"},
        headers={"X-User-Id": "bob_fin", "X-User-Groups": "group_finance"},
    )
    assert res_fin_ask.status_code == 200
    data_fin_ask = res_fin_ask.json()
    assert data_fin_ask["status"] == "ANSWERED"
    assert any(c["url"] == doc_fin.url for c in data_fin_ask["citations"])

    # -----------------------------------------------------------------------
    # Case D: Unauthorized / guest user attempts access
    # -----------------------------------------------------------------------
    res_guest_search = client.post(
        "/api/v1/search",
        json={"query": "Kubernetes cluster credentials or compensation bonus"},
        headers={"X-User-Id": "guest_user", "X-User-Groups": "group_guest"},
    )
    assert res_guest_search.status_code == 200
    assert res_guest_search.json()["totalResults"] == 0
