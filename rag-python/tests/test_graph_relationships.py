"""Focused unit and security tests for Knowledge Graph Entities and Relationships (AD-03).

Verifies:
1. Canonical relationship directions:
   - TICKET --discussed_in--> SLACK_THREAD
   - TICKET --implemented_by--> PULL_REQUEST
   - PULL_REQUEST --contains--> COMMIT
   - COMMIT --authored_by--> EMPLOYEE
   - No inverse relationships stored automatically.
2. Traversal directions: OUTGOING, INCOMING, BOTH.
3. Source record invariants:
   - TICKET and EMPLOYEE always have source_record_id = None.
   - PULL_REQUEST, COMMIT, and SLACK_THREAD require non-null source_record_id.
   - No promotion of TICKET or EMPLOYEE to anchored entities.
   - Detection of provenance conflicts on anchored entities.
4. Provenance visibility and dual-endpoint ACL isolation:
   - Unanchored entities are visible ONLY via authorized incident provenance.
   - Unauthorized relationship targets are pruned completely.
   - Secret tickets/employees mentioned only in restricted records return None.
5. Idempotency and duplicate prevention.
6. Pipeline integration with GitHub and Slack fixtures.
"""

from datetime import datetime, timezone

import pytest

from app.connectors.common.models import AclReference, PrincipalType, RawSourceItem, SourceType
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.graph.extractor import extract_entities_and_relationships
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import InMemoryKnowledgeRepository

# ---------------------------------------------------------------------------
# 1. Canonical Relationship Directions & Extraction
# ---------------------------------------------------------------------------

def test_canonical_relationship_directions():
    """Verify that extraction produces strictly canonical directions without inverse edges."""
    pr_item = RawSourceItem(
        id="raw:github:repo:pr:101",
        source_type=SourceType.GITHUB,
        source_id="101",
        source_url="https://github.com/company/repo/pull/101",
        title="Fix authentication flow (DC-100)",
        raw_content="Resolves ticket DC-100 with defensive checks",
        metadata={
            "repository": "company/repo",
            "kind": "pull_request",
            "number": 101,
            "ticket_ids": ["DC-100"],
            "commits": [{"sha": "c1001"}],
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    commit_item = RawSourceItem(
        id="raw:github:repo:commit:c1001",
        source_type=SourceType.GITHUB,
        source_id="c1001",
        source_url="https://github.com/company/repo/commit/c1001",
        title="Commit c1001",
        author_id="alex_dev",
        raw_content="Commit message referencing PR #101",
        metadata={
            "repository": "company/repo",
            "kind": "commit",
            "sha": "c1001",
            "author": {"login": "alex_dev", "name": "Alex Dev"},
            "ticket_ids": ["DC-100"],
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    slack_item = RawSourceItem(
        id="raw:slack:C01:160000.001",
        source_type=SourceType.SLACK,
        source_id="160000.001",
        source_url="https://slack.com/archives/C01/p160000001",
        title="Slack thread on DC-100",
        raw_content="Discussing DC-100 resolution",
        metadata={
            "channel_id": "C01",
            "channel_name": "backend",
            "thread_ts": "160000.001",
            "ticket_ids": ["DC-100"],
        },
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    entities, relationships = extract_entities_and_relationships([pr_item, commit_item, slack_item])
    rel_map = {(r.source_entity_id, r.target_entity_id): r.relationship_type for r in relationships}

    # 1. TICKET --discussed_in--> SLACK_THREAD
    assert rel_map.get(("ticket:DC-100", "slack:C01:160000.001")) == RelationshipType.DISCUSSED_IN.value
    # No inverse edge
    assert ("slack:C01:160000.001", "ticket:DC-100") not in rel_map

    # 2. TICKET --implemented_by--> PULL_REQUEST
    assert rel_map.get(("ticket:DC-100", "pr:company/repo:101")) == RelationshipType.IMPLEMENTED_BY.value
    # No inverse edge
    assert ("pr:company/repo:101", "ticket:DC-100") not in rel_map

    # 3. PULL_REQUEST --contains--> COMMIT
    assert rel_map.get(("pr:company/repo:101", "commit:company/repo:c1001")) == RelationshipType.CONTAINS.value
    # No inverse edge
    assert ("commit:company/repo:c1001", "pr:company/repo:101") not in rel_map

    # 4. COMMIT --authored_by--> EMPLOYEE
    assert rel_map.get(("commit:company/repo:c1001", "employee:alex_dev")) == RelationshipType.AUTHORED_BY.value
    # No inverse edge
    assert ("employee:alex_dev", "commit:company/repo:c1001") not in rel_map


# ---------------------------------------------------------------------------
# 2. Source Record Invariants
# ---------------------------------------------------------------------------

def test_unanchored_entities_always_have_null_source_record():
    """TICKET and EMPLOYEE must always have source_record_id = None."""
    repo = InMemoryKnowledgeRepository()
    ticket = Entity(
        id="ticket:T-1",
        entity_type=EntityType.TICKET.value,
        name="T-1",
        source_record_id="attempted_spoof_sr",  # Should be neutralized to None
    )
    employee = Entity(
        id="employee:john",
        entity_type=EntityType.EMPLOYEE.value,
        name="John Doe",
        source_record_id="attempted_spoof_sr",  # Should be neutralized to None
    )
    repo.save_entities([ticket, employee])

    assert repo.entities["ticket:T-1"].source_record_id is None
    assert repo.entities["employee:john"].source_record_id is None


def test_unanchored_entity_cannot_be_promoted_via_upsert():
    """Subsequent updates to TICKET or EMPLOYEE must not assign a non-null source_record_id."""
    repo = InMemoryKnowledgeRepository()
    ticket = Entity(id="ticket:T-2", entity_type=EntityType.TICKET.value, name="T-2", source_record_id=None)
    repo.save_entities([ticket])
    assert repo.entities["ticket:T-2"].source_record_id is None

    # Attempt promotion
    ticket_update = Entity(id="ticket:T-2", entity_type=EntityType.TICKET.value, name="T-2 Updated", source_record_id="raw:spoofed")
    repo.save_entities([ticket_update])

    assert repo.entities["ticket:T-2"].name == "T-2 Updated"
    assert repo.entities["ticket:T-2"].source_record_id is None


def test_anchored_entity_requires_non_null_source_record():
    """PULL_REQUEST, COMMIT, and SLACK_THREAD must fail if source_record_id is None."""
    repo = InMemoryKnowledgeRepository()
    bad_pr = Entity(id="pr:repo:1", entity_type=EntityType.PULL_REQUEST.value, name="PR 1", source_record_id=None)
    with pytest.raises(ValueError, match="requires a non-null source_record_id"):
        repo.save_entities([bad_pr])


def test_provenance_conflict_detected_and_rejected():
    """If an anchored entity receives a conflicting non-null source_record_id, reject with ValueError."""
    repo = InMemoryKnowledgeRepository()
    pr1 = Entity(id="pr:repo:10", entity_type=EntityType.PULL_REQUEST.value, name="PR 10", source_record_id="raw:source:A")
    repo.save_entities([pr1])

    # Conflicting provenance
    pr_conflict = Entity(id="pr:repo:10", entity_type=EntityType.PULL_REQUEST.value, name="PR 10", source_record_id="raw:source:B")
    with pytest.raises(ValueError, match="Provenance conflict"):
        repo.save_entities([pr_conflict])

    # Original state preserved
    assert repo.entities["pr:repo:10"].source_record_id == "raw:source:A"


# ---------------------------------------------------------------------------
# 3. Traversal Directions: OUTGOING, INCOMING, BOTH
# ---------------------------------------------------------------------------

def test_traversal_directions():
    repo = InMemoryKnowledgeRepository()

    # Entities
    ticket = Entity(id="ticket:T-3", entity_type=EntityType.TICKET.value, name="T-3")
    pr = Entity(id="pr:repo:30", entity_type=EntityType.PULL_REQUEST.value, name="PR 30", source_record_id="raw:pr:30")
    commit = Entity(id="commit:repo:c30", entity_type=EntityType.COMMIT.value, name="Commit c30", source_record_id="raw:commit:c30")
    repo.save_entities([ticket, pr, commit])

    # Grant public READ to both anchored entities
    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="raw:pr:30", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="raw:commit:c30", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
    ])

    # Relationships:
    # ticket:T-3 --implemented_by--> pr:repo:30
    # pr:repo:30 --contains--> commit:repo:c30
    repo.save_relationships([
        Relationship(source_entity_id="ticket:T-3", target_entity_id="pr:repo:30", relationship_type=RelationshipType.IMPLEMENTED_BY.value),
        Relationship(source_entity_id="pr:repo:30", target_entity_id="commit:repo:c30", relationship_type=RelationshipType.CONTAINS.value),
    ])

    # 1. OUTGOING from ticket:T-3 -> pr:repo:30
    out_ticket = repo.get_relationships_for_entity("ticket:T-3", direction="OUTGOING")
    assert len(out_ticket) == 1
    assert out_ticket[0][1].id == "pr:repo:30"
    assert out_ticket[0][0].relationship_type == RelationshipType.IMPLEMENTED_BY.value

    # 2. INCOMING from ticket:T-3 -> []
    inc_ticket = repo.get_relationships_for_entity("ticket:T-3", direction="INCOMING")
    assert len(inc_ticket) == 0

    # 3. INCOMING to pr:repo:30 -> ticket:T-3
    inc_pr = repo.get_relationships_for_entity("pr:repo:30", direction="INCOMING")
    assert len(inc_pr) == 1
    assert inc_pr[0][1].id == "ticket:T-3"

    # 4. OUTGOING from pr:repo:30 -> commit:repo:c30
    out_pr = repo.get_relationships_for_entity("pr:repo:30", direction="OUTGOING")
    assert len(out_pr) == 1
    assert out_pr[0][1].id == "commit:repo:c30"

    # 5. BOTH on pr:repo:30 -> both incoming ticket:T-3 and outgoing commit:repo:c30
    both_pr = repo.get_relationships_for_entity("pr:repo:30", direction="BOTH")
    assert len(both_pr) == 2
    neighbor_ids = {item[1].id for item in both_pr}
    assert neighbor_ids == {"ticket:T-3", "commit:repo:c30"}

    # 6. Invalid direction raises ValueError
    with pytest.raises(ValueError, match="Invalid traversal direction"):
        repo.get_relationships_for_entity("pr:repo:30", direction="SIDEWAYS")


# ---------------------------------------------------------------------------
# 4. Provenance Visibility & Dual-Endpoint ACL Isolation
# ---------------------------------------------------------------------------

def test_unanchored_entity_invisible_without_authorized_provenance():
    """A secret ticket mentioned only in a restricted source record returns None to unauthorized users."""
    repo = InMemoryKnowledgeRepository()
    ticket = Entity(id="ticket:SECRET-77", entity_type=EntityType.TICKET.value, name="SECRET-77")
    thread = Entity(
        id="slack:secret:1",
        entity_type=EntityType.SLACK_THREAD.value,
        name="Confidential Thread",
        source_record_id="raw:slack:secret",
    )
    repo.save_entities([ticket, thread])

    # Restricted to group_security
    repo.save_acls([
        AclReference(
            resource_type="SOURCE_RECORD",
            resource_id="raw:slack:secret",
            principal_type=PrincipalType.GROUP,
            principal_id="group_security",
            permission="READ",
        )
    ])
    repo.save_relationships([
        Relationship(source_entity_id="ticket:SECRET-77", target_entity_id="slack:secret:1", relationship_type=RelationshipType.DISCUSSED_IN.value)
    ])

    # Standard employee cannot see ticket or thread
    assert repo.get_entity("ticket:SECRET-77", user_id="dev_user", group_ids=["group_engineering"]) is None
    assert repo.get_entity("slack:secret:1", user_id="dev_user", group_ids=["group_engineering"]) is None
    assert repo.get_relationships_for_entity("ticket:SECRET-77", direction="BOTH", user_id="dev_user", group_ids=["group_engineering"]) == []

    # Security employee can see both
    sec_ticket = repo.get_entity("ticket:SECRET-77", user_id="sec_user", group_ids=["group_security"])
    assert sec_ticket is not None
    assert sec_ticket.name == "SECRET-77"
    sec_rels = repo.get_relationships_for_entity("ticket:SECRET-77", direction="OUTGOING", user_id="sec_user", group_ids=["group_security"])
    assert len(sec_rels) == 1
    assert sec_rels[0][1].id == "slack:secret:1"


def test_dual_endpoint_prunes_unauthorized_relationship_target():
    """Ticket T-PUB is implemented by public PR, but discussed in restricted Slack thread.

    Standard engineer must receive PR, but 0 traces of the secret Slack thread.
    """
    repo = InMemoryKnowledgeRepository()

    ticket = Entity(id="ticket:T-PUB", entity_type=EntityType.TICKET.value, name="T-PUB")
    pr_public = Entity(id="pr:repo:1", entity_type=EntityType.PULL_REQUEST.value, name="Public PR 1", source_record_id="raw:pr:pub")
    slack_secret = Entity(id="slack:priv:1", entity_type=EntityType.SLACK_THREAD.value, name="Private Slack", source_record_id="raw:slack:priv")
    repo.save_entities([ticket, pr_public, slack_secret])

    # PR is public; Slack thread is restricted to executive
    repo.save_acls([
        AclReference(resource_type="SOURCE_RECORD", resource_id="raw:pr:pub", principal_type=PrincipalType.PUBLIC, principal_id="*", permission="READ"),
        AclReference(resource_type="SOURCE_RECORD", resource_id="raw:slack:priv", principal_type=PrincipalType.GROUP, principal_id="group_exec", permission="READ"),
    ])

    repo.save_relationships([
        Relationship(source_entity_id="ticket:T-PUB", target_entity_id="pr:repo:1", relationship_type=RelationshipType.IMPLEMENTED_BY.value),
        Relationship(source_entity_id="ticket:T-PUB", target_entity_id="slack:priv:1", relationship_type=RelationshipType.DISCUSSED_IN.value),
    ])

    # Standard engineer queries ticket:T-PUB relationships
    eng_rels = repo.get_relationships_for_entity("ticket:T-PUB", direction="OUTGOING", user_id="alice", group_ids=["group_engineering"])
    assert len(eng_rels) == 1
    assert eng_rels[0][1].id == "pr:repo:1"
    # Privileged slack thread is NOT in results
    assert "slack:priv:1" not in {item[1].id for item in eng_rels}

    # Executive queries ticket:T-PUB relationships -> receives both
    exec_rels = repo.get_relationships_for_entity("ticket:T-PUB", direction="OUTGOING", user_id="bob", group_ids=["group_exec"])
    assert len(exec_rels) == 2
    assert {item[1].id for item in exec_rels} == {"pr:repo:1", "slack:priv:1"}


# ---------------------------------------------------------------------------
# 5. Idempotency & Upsert Tests
# ---------------------------------------------------------------------------

def test_idempotent_entity_and_relationship_persistence():
    """Saving identical entities and relationships twice does not duplicate records."""
    repo = InMemoryKnowledgeRepository()
    ticket = Entity(id="ticket:T-IDEMP", entity_type=EntityType.TICKET.value, name="T-IDEMP")
    pr = Entity(id="pr:repo:200", entity_type=EntityType.PULL_REQUEST.value, name="PR 200", source_record_id="raw:pr:200")
    rel = Relationship(source_entity_id="ticket:T-IDEMP", target_entity_id="pr:repo:200", relationship_type=RelationshipType.IMPLEMENTED_BY.value)

    repo.save_entities([ticket, pr])
    repo.save_relationships([rel])
    assert len(repo.entities) == 2
    assert len(repo.relationships) == 1

    # Second save with updated metadata
    ticket_up = Entity(id="ticket:T-IDEMP", entity_type=EntityType.TICKET.value, name="T-IDEMP (v2)", metadata={"priority": "high"})
    rel_up = Relationship(source_entity_id="ticket:T-IDEMP", target_entity_id="pr:repo:200", relationship_type=RelationshipType.IMPLEMENTED_BY.value, metadata={"state": "merged"})
    repo.save_entities([ticket_up])
    repo.save_relationships([rel_up])

    assert len(repo.entities) == 2
    assert len(repo.relationships) == 1
    assert repo.entities["ticket:T-IDEMP"].name == "T-IDEMP (v2)"
    assert repo.entities["ticket:T-IDEMP"].metadata.get("priority") == "high"


# ---------------------------------------------------------------------------
# 6. End-to-End Pipeline Ingestion Integration
# ---------------------------------------------------------------------------

def test_ingestion_pipeline_extracts_and_persists_graph():
    """Verify that IngestionPipeline automatically extracts entities and relationships."""
    repo = InMemoryKnowledgeRepository()
    embeddings = MockEmbeddingProvider()

    # 1. Ingest GitHub
    github_pipeline = IngestionPipeline(
        connector=GitHubFixtureAdapter(),
        repository=repo,
        embedding_provider=embeddings,
    )
    github_pipeline.run()

    # 2. Ingest Slack
    slack_pipeline = IngestionPipeline(
        connector=SlackFixtureAdapter(),
        repository=repo,
        embedding_provider=embeddings,
    )
    slack_pipeline.run()

    # Check entities
    assert len(repo.entities) > 0
    # DC-8692 ticket should exist
    assert "ticket:DC-8692" in repo.entities
    assert repo.entities["ticket:DC-8692"].source_record_id is None

    # Check relationships
    assert len(repo.relationships) > 0

    # Query relationships as engineering user (authorized by fixture ACLs)
    eng_context = ("employee_42", ["group_engineering", "group_backend"])
    ticket_rels = repo.get_relationships_for_entity(
        "ticket:DC-8692",
        direction="OUTGOING",
        user_id=eng_context[0],
        group_ids=eng_context[1],
    )
    assert len(ticket_rels) > 0
    rel_types = {item[0].relationship_type for item in ticket_rels}
    assert RelationshipType.IMPLEMENTED_BY.value in rel_types
    assert RelationshipType.DISCUSSED_IN.value in rel_types

    # Query with unauthorized user (marketing) -> returns empty list (provenance isolation)
    unauth_rels = repo.get_relationships_for_entity(
        "ticket:DC-8692",
        direction="OUTGOING",
        user_id="marketing_user",
        group_ids=["group_marketing"],
    )
    assert len(unauth_rels) == 0


# ---------------------------------------------------------------------------
# 7. Batch Provenance Validation & Atomicity Tests
# ---------------------------------------------------------------------------

def test_batch_conflict_leaves_no_partial_in_memory_changes():
    """If an entity late in a batch fails validation, no earlier entity in that batch persists."""
    repo = InMemoryKnowledgeRepository()
    assert len(repo.entities) == 0

    valid1 = Entity(id="pr:batch:1", entity_type=EntityType.PULL_REQUEST.value, name="PR 1", source_record_id="raw:pr:1")
    valid2 = Entity(id="ticket:batch:1", entity_type=EntityType.TICKET.value, name="Ticket 1")
    conflicting3 = Entity(id="pr:batch:1", entity_type=EntityType.PULL_REQUEST.value, name="PR 1 Conflict", source_record_id="raw:pr:DIFFERENT")

    with pytest.raises(ValueError, match="Provenance conflict within batch"):
        repo.save_entities([valid1, valid2, conflicting3])

    # In-memory repository state must remain completely empty (no partial persistence)
    assert len(repo.entities) == 0
    assert "pr:batch:1" not in repo.entities
    assert "ticket:batch:1" not in repo.entities


def test_intra_batch_conflicting_duplicate_rejected():
    """Duplicate entity IDs within the same batch cannot have conflicting non-null source_record_id."""
    repo = InMemoryKnowledgeRepository()

    dup_a = Entity(id="pr:dup:1", entity_type=EntityType.PULL_REQUEST.value, name="PR v1", source_record_id="raw:source:A")
    dup_b = Entity(id="pr:dup:1", entity_type=EntityType.PULL_REQUEST.value, name="PR v2", source_record_id="raw:source:B")

    with pytest.raises(ValueError, match="Provenance conflict within batch"):
        repo.save_entities([dup_a, dup_b])

    assert len(repo.entities) == 0


def test_existing_state_conflicting_rejected():
    """Incoming entity cannot conflict with existing persisted non-null source_record_id."""
    repo = InMemoryKnowledgeRepository()
    pr1 = Entity(id="pr:exist:1", entity_type=EntityType.PULL_REQUEST.value, name="PR Orig", source_record_id="raw:source:ORIG")
    repo.save_entities([pr1])

    # Conflict against existing persisted state
    pr1_conflict = Entity(id="pr:exist:1", entity_type=EntityType.PULL_REQUEST.value, name="PR Conflict", source_record_id="raw:source:OTHER")
    with pytest.raises(ValueError, match="Provenance conflict for entity 'pr:exist:1'"):
        repo.save_entities([pr1_conflict])

    # State remains untouched
    assert repo.entities["pr:exist:1"].source_record_id == "raw:source:ORIG"
    assert repo.entities["pr:exist:1"].name == "PR Orig"


def test_intra_batch_identical_duplicates_with_matching_source_record_succeed():
    """Identical duplicate IDs with matching source_record_id succeed and idempotently update."""
    repo = InMemoryKnowledgeRepository()

    dup_1 = Entity(id="pr:idem:1", entity_type=EntityType.PULL_REQUEST.value, name="PR Initial", source_record_id="raw:source:MATCH", metadata={"step": 1})
    dup_2 = Entity(id="pr:idem:1", entity_type=EntityType.PULL_REQUEST.value, name="PR Final", source_record_id="raw:source:MATCH", metadata={"step": 2, "ok": True})

    repo.save_entities([dup_1, dup_2])

    assert len(repo.entities) == 1
    saved = repo.entities["pr:idem:1"]
    assert saved.source_record_id == "raw:source:MATCH"
    assert saved.name == "PR Final"
    assert saved.metadata["step"] == 2
    assert saved.metadata["ok"] is True


def test_ticket_and_employee_remain_unanchored():
    """TICKET and EMPLOYEE always have source_record_id = None across batches and updates."""
    repo = InMemoryKnowledgeRepository()

    ticket = Entity(id="ticket:T-STAY", entity_type=EntityType.TICKET.value, name="T-STAY", source_record_id="raw:spoof1")
    employee = Entity(id="employee:E-STAY", entity_type=EntityType.EMPLOYEE.value, name="E-STAY", source_record_id="raw:spoof2")

    repo.save_entities([ticket, employee])
    assert repo.entities["ticket:T-STAY"].source_record_id is None
    assert repo.entities["employee:E-STAY"].source_record_id is None

    # Subsequent update batch
    ticket_up = Entity(id="ticket:T-STAY", entity_type=EntityType.TICKET.value, name="T-STAY Updated", source_record_id="raw:spoof3")
    employee_up = Entity(id="employee:E-STAY", entity_type=EntityType.EMPLOYEE.value, name="E-STAY Updated", source_record_id=None)

    repo.save_entities([ticket_up, employee_up])
    assert repo.entities["ticket:T-STAY"].source_record_id is None
    assert repo.entities["ticket:T-STAY"].name == "T-STAY Updated"
    assert repo.entities["employee:E-STAY"].source_record_id is None
    assert repo.entities["employee:E-STAY"].name == "E-STAY Updated"


def test_state_remains_unchanged_after_failed_batch_with_prior_entities():
    """If repository already has data and a new batch fails, prior state is completely preserved."""
    repo = InMemoryKnowledgeRepository()

    pr_prior = Entity(id="pr:prior:1", entity_type=EntityType.PULL_REQUEST.value, name="PR Prior", source_record_id="raw:pr:prior")
    ticket_prior = Entity(id="ticket:prior:1", entity_type=EntityType.TICKET.value, name="Ticket Prior")
    repo.save_entities([pr_prior, ticket_prior])

    # Failing batch containing new entities followed by a conflicting entity
    pr_new = Entity(id="pr:new:1", entity_type=EntityType.PULL_REQUEST.value, name="PR New", source_record_id="raw:pr:new")
    pr_conflict = Entity(id="pr:prior:1", entity_type=EntityType.PULL_REQUEST.value, name="PR Prior Mod", source_record_id="raw:pr:CONFLICT")

    with pytest.raises(ValueError, match="Provenance conflict"):
        repo.save_entities([pr_new, pr_conflict])

    # Verify prior state unchanged and new entities NOT inserted
    assert len(repo.entities) == 2
    assert "pr:new:1" not in repo.entities
    assert repo.entities["pr:prior:1"].name == "PR Prior"
    assert repo.entities["pr:prior:1"].source_record_id == "raw:pr:prior"


# ---------------------------------------------------------------------------
# 8. PostgreSQL Save Entities Logic & Transaction Unit Tests (Mocked DB)
# ---------------------------------------------------------------------------

def test_postgres_save_entities_prevalidation_rejects_intra_batch_conflict():
    """PostgresKnowledgeRepository pre-validation rejects intra-batch conflict before DB calls."""
    from app.indexing.repository import PostgresKnowledgeRepository

    repo = PostgresKnowledgeRepository("postgresql://mock/db")
    dup_a = Entity(id="pr:pg:1", entity_type=EntityType.PULL_REQUEST.value, name="PR 1", source_record_id="raw:source:A")
    dup_b = Entity(id="pr:pg:1", entity_type=EntityType.PULL_REQUEST.value, name="PR 2", source_record_id="raw:source:B")

    with pytest.raises(ValueError, match="Provenance conflict within batch"):
        repo.save_entities([dup_a, dup_b])


def test_postgres_save_entities_conflict_aware_sql_and_rollback(monkeypatch):
    """PostgresKnowledgeRepository executes in transaction and rolls back when WHERE condition fails."""
    from unittest.mock import MagicMock

    from app.indexing.repository import PostgresKnowledgeRepository

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_tx = MagicMock()
    mock_conn.transaction.return_value.__enter__.return_value = mock_tx
    mock_conn.transaction.return_value.__exit__.return_value = None

    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_conn.cursor.return_value.__exit__.return_value = None

    repo = PostgresKnowledgeRepository("postgresql://mock/db")
    monkeypatch.setattr(repo, "_get_connection", lambda: mock_conn)

    # Pre-check returns empty (no row in DB at pre-check time)
    mock_cur.fetchall.return_value = []
    # Conflict occurs: INSERT ON CONFLICT RETURNING id returns None
    mock_cur.fetchone.side_effect = [None, ("raw:other",)]

    pr = Entity(id="pr:pg:2", entity_type=EntityType.PULL_REQUEST.value, name="PR 2", source_record_id="raw:source:MINE")

    with pytest.raises(ValueError, match="Provenance conflict for entity 'pr:pg:2'"):
        repo.save_entities([pr])

    # Assert transaction was entered
    assert mock_conn.transaction.called
    # Assert query had conflict detection clause
    executed_queries = [call[0][0] for call in mock_cur.execute.call_args_list]
    upsert_call = [q for q in executed_queries if "INSERT INTO entities" in q][0]
    assert "IS NOT DISTINCT FROM EXCLUDED.source_record_id" in upsert_call
    assert "RETURNING id" in upsert_call
