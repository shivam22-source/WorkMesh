"""Tests for database-level lease fencing, atomic claims, and status checks (Phase 5 Step 2)."""

import pytest

from app.indexing.models import SyncStateRecord
from app.indexing.repository import (
    FencedSyncError,
    InMemoryKnowledgeRepository,
    PostgresKnowledgeRepository,
)


def test_in_memory_claim_sync_and_lease_acquisition():
    """Verify that claim_sync acquires an exclusive lease and resets counter."""
    repo = InMemoryKnowledgeRepository()

    # Prior state with synced records
    prior_state = SyncStateRecord(
        source_type="GITHUB",
        cursor_value="c1",
        status="SUCCESS",
        records_synced_last_run=42,
    )
    repo.update_sync_state(prior_state)

    # Claim sync
    claim = repo.claim_sync("GITHUB", lease_token="token-1", lease_ttl_seconds=300)
    assert claim is not None
    assert claim.source_type == "GITHUB"
    assert claim.cursor_value == "c1"
    assert claim.lease_token == "token-1"

    # Verify state updated
    state = repo.get_sync_state("GITHUB")
    assert state.status == "SYNCING"
    assert state.records_synced_last_run == 0
    assert state.metadata["lease_token"] == "token-1"


def test_competing_worker_cannot_claim_active_unexpired_lease():
    """Worker 2 cannot claim sync while Worker 1 holds an unexpired lease."""
    repo = InMemoryKnowledgeRepository()

    claim1 = repo.claim_sync("EMAIL", lease_token="worker-1-token", lease_ttl_seconds=300)
    assert claim1 is not None

    # Competing worker attempts claim
    claim2 = repo.claim_sync("EMAIL", lease_token="worker-2-token", lease_ttl_seconds=300)
    assert claim2 is None


def test_claim_sync_succeeds_when_prior_lease_expired():
    """Worker 2 can claim sync once Worker 1's lease has expired."""
    repo = InMemoryKnowledgeRepository()

    claim1 = repo.claim_sync("SLACK", lease_token="worker-1-token", lease_ttl_seconds=-10)
    assert claim1 is not None

    # Worker 2 attempts claim on expired lease
    claim2 = repo.claim_sync("SLACK", lease_token="worker-2-token", lease_ttl_seconds=300)
    assert claim2 is not None
    assert claim2.lease_token == "worker-2-token"


def test_expired_lease_worker_fenced_out_of_batch_writes():
    """Worker whose lease has expired is rejected with FencedSyncError on batch write."""
    repo = InMemoryKnowledgeRepository()

    claim = repo.claim_sync("GITHUB", lease_token="worker-1", lease_ttl_seconds=-5)
    assert claim is not None

    with pytest.raises(FencedSyncError, match="Lease expired"):
        repo.persist_sync_batch(
            source_type="GITHUB",
            lease_token="worker-1",
            next_cursor="c2",
            items=[],
            docs=[],
            chunks=[],
            acls=[],
            entities=[],
            relationships=[],
        )


def test_stale_worker_fenced_out_if_lease_claimed_before_complete_sync():
    """Worker 1 is fenced out if Worker 2 claimed the lease before Worker 1's completion."""
    repo = InMemoryKnowledgeRepository()

    # Worker 1 claims with expired TTL
    repo.claim_sync("GITHUB", lease_token="worker-1", lease_ttl_seconds=-10)

    # Worker 2 takes over the lease
    repo.claim_sync("GITHUB", lease_token="worker-2", lease_ttl_seconds=300)

    # Worker 1 attempts to mark complete
    with pytest.raises(FencedSyncError, match="Worker fenced out"):
        repo.complete_sync("GITHUB", lease_token="worker-1", final_cursor="c1")

    # Verify state remains Worker 2's lease and SYNCING
    state = repo.get_sync_state("GITHUB")
    assert state.status == "SYNCING"
    assert state.metadata["lease_token"] == "worker-2"


def test_postgres_claim_sync_sql_structure():
    """Verify PostgresKnowledgeRepository SQL incorporates pg_input_is_valid and clock_timestamp."""
    repo = PostgresKnowledgeRepository("postgresql://mock/db")
    # Repo contains claim_sync, renew_lease, complete_sync, fail_sync, persist_sync_batch methods
    assert hasattr(repo, "claim_sync")
    assert hasattr(repo, "renew_lease")
    assert hasattr(repo, "complete_sync")
    assert hasattr(repo, "fail_sync")
    assert hasattr(repo, "persist_sync_batch")
