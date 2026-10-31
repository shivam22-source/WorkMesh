"""Unit tests for DeterministicReranker: calibrated boosting, diversity discounting, and entity resolution."""

import random
import pytest

from app.connectors.common.models import AclReference, PrincipalType
from app.contracts.rag_search import RagSearchResultItem
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.repository import InMemoryKnowledgeRepository
from app.rag.reranker import DeterministicReranker, map_document_id_to_entity_id


# ---------------------------------------------------------------------------
# 1. Verified Document ID to Entity ID Mapping
# ---------------------------------------------------------------------------

def test_map_document_id_to_entity_id():
    """Verify exact mappings from normalizer document IDs to canonical entity IDs."""
    # 1. GitHub PR
    assert map_document_id_to_entity_id("doc:github:company/repo:pr:101") == "pr:company/repo:101"

    # 2. GitHub Commit
    assert map_document_id_to_entity_id("doc:github:company/repo:commit:8af2d1e94b2a8d3e") == "commit:company/repo:8af2d1e94b2a8d3e"

    # 3. Slack Thread (:thread: in doc_id, omitted in entity_id)
    assert map_document_id_to_entity_id("doc:slack:C01:thread:160000.001") == "slack:C01:160000.001"

    # 4. Unknown or unverified format returns None safely
    assert map_document_id_to_entity_id("doc:custom:source:unknown") is None
    assert map_document_id_to_entity_id("") is None


# ---------------------------------------------------------------------------
# 2. Close RRF Score Reordering & Marginal Match Protection
# ---------------------------------------------------------------------------

def test_close_rrf_scores_reordered_by_relationship_and_phrase_bonus():
    """When candidates have close RRF scores (delta < 0.0030), relationship boost intentionally reorders them."""
    repo = InMemoryKnowledgeRepository()

    # ticket:DC-100 --implemented_by--> pr:company/repo:101
    ticket = Entity(id="ticket:DC-100", entity_type=EntityType.TICKET.value, name="DC-100")
    pr_entity = Entity(id="pr:company/repo:101", entity_type=EntityType.PULL_REQUEST.value, name="PR 101", source_record_id="github:company/repo:pr:101")
    repo.save_entities([ticket, pr_entity])
    repo.save_relationships([
        Relationship(source_entity_id="ticket:DC-100", target_entity_id="pr:company/repo:101", relationship_type=RelationshipType.IMPLEMENTED_BY.value)
    ])
    # Grant READ ACL to anchored PR so provenance is authorized
    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="github:company/repo:pr:101", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ")
    ])

    reranker = DeterministicReranker(repository=repo)

    # Candidate 1: Generic candidate without relationship (Rank 1 consensus: 0.0328)
    cand1 = RagSearchResultItem(
        chunk_id="c1",
        document_id="doc:github:company/repo:pr:99",
        source_type="GITHUB",
        title="Generic Auth Fix",
        snippet="Updated authentication validation helper",
        source_url="https://github.com/company/repo/pull/99",
        score=0.0328,
    )
    # Candidate 2: Close retrieval consensus (0.0323), but implements DC-100 (+0.0020 boost)
    cand2 = RagSearchResultItem(
        chunk_id="c2",
        document_id="doc:github:company/repo:pr:101",
        source_type="GITHUB",
        title="Fix validation flow",
        snippet="Resolves ticket DC-100 defensive checks",
        source_url="https://github.com/company/repo/pull/101",
        score=0.0323,
    )

    reranked = reranker.rerank(query="why did DC-100 change validation?", candidates=[cand1, cand2])

    assert len(reranked) == 2
    # Candidate 2 receives relationship boost (0.0323 + 0.0020 = 0.0343) and overtakes Candidate 1 (0.0328)
    assert reranked[0].chunk_id == "c2"
    assert reranked[0].score > reranked[1].score
    assert reranked[1].chunk_id == "c1"


def test_marginal_match_cannot_overwhelm_strong_retrieval_consensus():
    """A weak single-modality candidate (+0.0020 boost) can never overtake a strong consensus candidate."""
    repo = InMemoryKnowledgeRepository()
    ticket = Entity(id="ticket:DC-200", entity_type=EntityType.TICKET.value, name="DC-200")
    pr_entity = Entity(id="pr:company/repo:202", entity_type=EntityType.PULL_REQUEST.value, name="PR 202", source_record_id="github:company/repo:pr:202")
    repo.save_entities([ticket, pr_entity])
    repo.save_relationships([
        Relationship(source_entity_id="ticket:DC-200", target_entity_id="pr:company/repo:202", relationship_type=RelationshipType.IMPLEMENTED_BY.value)
    ])

    reranker = DeterministicReranker(repository=repo)

    # Strong multi-modal consensus (0.0328), no relationship
    cand_strong = RagSearchResultItem(
        chunk_id="c_strong",
        document_id="doc:github:company/repo:pr:999",
        source_type="GITHUB",
        title="Core auth engine",
        snippet="Primary authentication logic changes",
        source_url="https://github.com/company/repo/pull/999",
        score=0.0328,
    )
    # Weak candidate (0.0133), has relationship boost (+0.0020) and text bonus (+0.0010 max)
    cand_weak = RagSearchResultItem(
        chunk_id="c_weak",
        document_id="doc:github:company/repo:pr:202",
        source_type="GITHUB",
        title="DC-200 docs update",
        snippet="Minor documentation for DC-200",
        source_url="https://github.com/company/repo/pull/202",
        score=0.0133,
    )

    reranked = reranker.rerank(query="DC-200 authentication", candidates=[cand_strong, cand_weak])

    assert len(reranked) == 2
    # Strong candidate remains firmly #1 (0.0328 >> 0.0133 + 0.0030 = 0.0163)
    assert reranked[0].chunk_id == "c_strong"
    assert reranked[1].chunk_id == "c_weak"


# ---------------------------------------------------------------------------
# 3. Deterministic Diversity Discounting & Input-Order Invariance
# ---------------------------------------------------------------------------

def test_deterministic_diversity_discounting_enables_multi_source_representation():
    """Second chunk of same document receives 0.80 factor, allowing diverse source candidate to rank higher."""
    reranker = DeterministicReranker()

    # Document A (PR 101): Chunk 0 (0.0328) and Chunk 1 (0.0323)
    cand_a0 = RagSearchResultItem(
        chunk_id="chunk_a0",
        document_id="doc:github:company/repo:pr:101",
        source_type="GITHUB",
        title="PR 101: Part 1",
        snippet="Overview description of PR 101",
        source_url="https://github.com/company/repo/pull/101",
        score=0.0328,
    )
    cand_a1 = RagSearchResultItem(
        chunk_id="chunk_a1",
        document_id="doc:github:company/repo:pr:101",
        source_type="GITHUB",
        title="PR 101: Part 2",
        snippet="File changes detail for PR 101",
        source_url="https://github.com/company/repo/pull/101",
        score=0.0323,
    )
    # Document B (Slack Thread): Chunk 0 (0.0300)
    cand_b0 = RagSearchResultItem(
        chunk_id="chunk_b0",
        document_id="doc:slack:C01:thread:160000.001",
        source_type="SLACK",
        title="Discussion on PR 101",
        snippet="Team discussion in Slack about architecture",
        source_url="https://company.slack.com/archives/C01/p160000001",
        score=0.0300,
    )

    reranked = reranker.rerank(query="architecture discussion", candidates=[cand_a0, cand_a1, cand_b0])

    assert len(reranked) == 3
    # cand_a0: rank 0 in doc A -> factor 1.0 (score ~0.0328)
    assert reranked[0].chunk_id == "chunk_a0"
    # cand_b0: rank 0 in doc B -> factor 1.0 (score ~0.0300) -> ranks ahead of cand_a1 (0.0323 * 0.80 = 0.02584)
    assert reranked[1].chunk_id == "chunk_b0"
    assert reranked[2].chunk_id == "chunk_a1"


def test_reranker_output_is_invariant_to_input_ordering_and_tied_scores():
    """Reranker produces 100% identical output order regardless of candidate input permutation, even with tied RRF scores."""
    reranker = DeterministicReranker()

    cand1 = RagSearchResultItem(chunk_id="chunk_1", document_id="doc:1", source_type="GITHUB", title="T1", snippet="S1", source_url="u1", score=0.0300)
    cand2 = RagSearchResultItem(chunk_id="chunk_2", document_id="doc:1", source_type="GITHUB", title="T2", snippet="S2", source_url="u2", score=0.0300)  # Tied score, same doc
    cand3 = RagSearchResultItem(chunk_id="chunk_3", document_id="doc:2", source_type="SLACK", title="T3", snippet="S3", source_url="u3", score=0.0280)
    cand4 = RagSearchResultItem(chunk_id="chunk_4", document_id="doc:3", source_type="GITHUB", title="T4", snippet="S4", source_url="u4", score=0.0250)

    base_list = [cand1, cand2, cand3, cand4]
    reversed_list = [cand4, cand3, cand2, cand1]
    shuffled_list = [cand3, cand1, cand4, cand2]

    res_base = [c.chunk_id for c in reranker.rerank("test query", base_list)]
    res_rev = [c.chunk_id for c in reranker.rerank("test query", reversed_list)]
    res_shuf = [c.chunk_id for c in reranker.rerank("test query", shuffled_list)]

    assert res_base == res_rev
    assert res_base == res_shuf
    # Tied chunks within doc:1 resolved deterministically by chunk_id ASC (chunk_1 factor 1.0, chunk_2 factor 0.80)
    assert res_base[0] == "chunk_1"
    assert res_base[1] == "chunk_3"  # doc:2 (0.0280) beats chunk_2 (0.0300 * 0.80 = 0.0240)
    assert res_base[2] == "chunk_4"  # doc:3 (0.0250) beats chunk_2 (0.0240)
    assert res_base[3] == "chunk_2"


# ---------------------------------------------------------------------------
# 4. Ambiguous vs Unambiguous Entity Resolution
# ---------------------------------------------------------------------------

def test_ambiguous_pr_number_skips_relationship_boost():
    """If PR #101 appears in multiple repositories in candidate pool, skip relationship boosting."""
    repo = InMemoryKnowledgeRepository()
    # Relations configured for alpha's PR 101 only
    pr_alpha = Entity(id="pr:org/service-alpha:101", entity_type=EntityType.PULL_REQUEST.value, name="PR 101 Alpha", source_record_id="github:org/service-alpha:pr:101")
    commit_alpha = Entity(id="commit:org/service-alpha:c100101", entity_type=EntityType.COMMIT.value, name="Commit Alpha", source_record_id="github:org/service-alpha:commit:c100101")
    repo.save_entities([pr_alpha, commit_alpha])
    repo.save_relationships([
        Relationship(source_entity_id="pr:org/service-alpha:101", target_entity_id="commit:org/service-alpha:c100101", relationship_type=RelationshipType.CONTAINS.value)
    ])
    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="github:org/service-alpha:pr:101", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="github:org/service-alpha:commit:c100101", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
    ])

    reranker = DeterministicReranker(repository=repo)

    # Candidate pool contains PR 101 from TWO different repositories
    cand_alpha = RagSearchResultItem(chunk_id="c_alpha", document_id="doc:github:org/service-alpha:pr:101", source_type="GITHUB", title="PR 101 Alpha", snippet="...", source_url="...", score=0.0200)
    cand_beta = RagSearchResultItem(chunk_id="c_beta", document_id="doc:github:org/service-beta:pr:101", source_type="GITHUB", title="PR 101 Beta", snippet="...", source_url="...", score=0.0200)

    # Candidate commit that would receive boost if PR 101 was resolved
    cand_commit = RagSearchResultItem(chunk_id="c_commit", document_id="doc:github:org/service-alpha:commit:c100101", source_type="GITHUB", title="Commit c100101", snippet="...", source_url="...", score=0.0190)

    # Query with ambiguous "PR #101"
    reranked = reranker.rerank(query="what changed in PR #101?", candidates=[cand_alpha, cand_beta, cand_commit])

    commit_res = [c for c in reranked if c.chunk_id == "c_commit"][0]
    # Commit did not receive the +0.0020 relationship boost because PR #101 was ambiguous across alpha and beta
    assert commit_res.score < 0.0200


def test_unambiguous_pr_number_receives_relationship_boost():
    """If PR #101 appears in exactly one repository in candidate pool, resolve and boost connected entities."""
    repo = InMemoryKnowledgeRepository()
    pr_alpha = Entity(id="pr:org/service-alpha:101", entity_type=EntityType.PULL_REQUEST.value, name="PR 101 Alpha", source_record_id="github:org/service-alpha:pr:101")
    commit_alpha = Entity(id="commit:org/service-alpha:c100101", entity_type=EntityType.COMMIT.value, name="Commit Alpha", source_record_id="github:org/service-alpha:commit:c100101")
    repo.save_entities([pr_alpha, commit_alpha])
    repo.save_relationships([
        Relationship(source_entity_id="pr:org/service-alpha:101", target_entity_id="commit:org/service-alpha:c100101", relationship_type=RelationshipType.CONTAINS.value)
    ])
    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="github:org/service-alpha:pr:101", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="github:org/service-alpha:commit:c100101", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
    ])

    reranker = DeterministicReranker(repository=repo)

    # Candidate pool contains PR 101 only from service-alpha
    cand_alpha = RagSearchResultItem(chunk_id="c_alpha", document_id="doc:github:org/service-alpha:pr:101", source_type="GITHUB", title="PR 101 Alpha", snippet="...", source_url="...", score=0.0200)
    cand_commit = RagSearchResultItem(chunk_id="c_commit", document_id="doc:github:org/service-alpha:commit:c100101", source_type="GITHUB", title="Commit c100101", snippet="...", source_url="...", score=0.0190)

    reranked = reranker.rerank(query="what changed in PR #101?", candidates=[cand_alpha, cand_commit])

    commit_res = [c for c in reranked if c.chunk_id == "c_commit"][0]
    # Commit received +0.0020 relationship boost (0.0190 + 0.0020 = 0.0210), overtaking PR (0.0200)
    assert commit_res.score >= 0.0210
    assert reranked[0].chunk_id == "c_commit"


def test_commit_hash_length_and_ambiguity():
    """Commit hash requires >= 7 hex characters and unambiguous candidate repository."""
    repo = InMemoryKnowledgeRepository()
    commit_alpha = Entity(id="commit:org/service-alpha:8af2d1e94b2a8d3e", entity_type=EntityType.COMMIT.value, name="Commit 8af2d1e", source_record_id="github:org/service-alpha:commit:8af2d1e94b2a8d3e")
    pr_alpha = Entity(id="pr:org/service-alpha:101", entity_type=EntityType.PULL_REQUEST.value, name="PR 101", source_record_id="github:org/service-alpha:pr:101")
    repo.save_entities([commit_alpha, pr_alpha])
    repo.save_relationships([
        Relationship(source_entity_id="pr:org/service-alpha:101", target_entity_id="commit:org/service-alpha:8af2d1e94b2a8d3e", relationship_type=RelationshipType.CONTAINS.value)
    ])
    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="github:org/service-alpha:pr:101", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="github:org/service-alpha:commit:8af2d1e94b2a8d3e", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
    ])

    reranker = DeterministicReranker(repository=repo)

    cand_commit = RagSearchResultItem(chunk_id="c_sha", document_id="doc:github:org/service-alpha:commit:8af2d1e94b2a8d3e", source_type="GITHUB", title="C", snippet="...", source_url="...", score=0.0200)
    cand_pr = RagSearchResultItem(chunk_id="c_pr", document_id="doc:github:org/service-alpha:pr:101", source_type="GITHUB", title="P", snippet="...", source_url="...", score=0.0190)

    # 1. Short prefix (< 7 chars, e.g. "8af2d") is ignored by regex -> boost skipped
    reranked_short = reranker.rerank(query="changes in 8af2d", candidates=[cand_commit, cand_pr])
    pr_short = [c for c in reranked_short if c.chunk_id == "c_pr"][0]
    assert pr_short.score == 0.0190

    # 2. 7-char prefix ("8af2d1e") unambiguously matches service-alpha -> boost applied to PR
    reranked_valid = reranker.rerank(query="changes in 8af2d1e", candidates=[cand_commit, cand_pr])
    pr_valid = [c for c in reranked_valid if c.chunk_id == "c_pr"][0]
    assert pr_valid.score >= 0.0210
