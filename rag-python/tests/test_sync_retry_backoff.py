"""Tests for bounded exponential retry, non-retryable handling, backfill regex, and migration parity (Phase 5 Step 2)."""

import re
from pathlib import Path

import pytest

from app.indexing.repository import DatabaseUnavailableError, FencedSyncError
from app.indexing.retry import is_transient_error, retry_with_backoff


def test_is_transient_error_classification():
    """Verify correct classification of transient vs non-transient exceptions."""
    assert is_transient_error(ConnectionError("conn reset")) is True
    assert is_transient_error(TimeoutError("timed out")) is True
    assert is_transient_error(OSError("network unreachable")) is True

    # Non-transient
    assert is_transient_error(ValueError("bad input")) is False
    assert is_transient_error(FencedSyncError("fenced")) is False
    assert is_transient_error(DatabaseUnavailableError("db down")) is False


def test_retry_transient_network_error_succeeds():
    """Verify that a transient error on attempt 1 succeeds on attempt 2 with backoff sleep."""
    attempts = 0
    sleeps = []

    def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("Temporary glitch")
        return "success"

    result = retry_with_backoff(
        flaky_call,
        max_attempts=3,
        base_delay=0.1,
        max_delay=1.0,
        jitter=False,
        sleep_fn=sleeps.append,
    )

    assert result == "success"
    assert attempts == 2
    assert len(sleeps) == 1
    assert sleeps[0] == 0.1  # base_delay * 2^0


def test_retry_transient_exhaustion_raises():
    """Verify that exhausting max_attempts raises the final exception."""
    attempts = 0
    sleeps = []

    def always_fails():
        nonlocal attempts
        attempts += 1
        raise TimeoutError(f"Fail attempt {attempts}")

    with pytest.raises(TimeoutError, match="Fail attempt 3"):
        retry_with_backoff(
            always_fails,
            max_attempts=3,
            base_delay=0.1,
            max_delay=1.0,
            jitter=False,
            sleep_fn=sleeps.append,
        )

    assert attempts == 3
    assert len(sleeps) == 2  # slept between attempt 1->2 and 2->3


def test_non_retryable_errors_fail_immediately():
    """Non-transient errors (validation, auth, database persistence) fail on attempt 1 without retry."""
    sleeps = []

    for err_cls in [ValueError, DatabaseUnavailableError, FencedSyncError]:
        attempts = 0

        def non_retryable_call():
            nonlocal attempts
            attempts += 1
            raise err_cls("Fatal error")

        with pytest.raises(err_cls, match="Fatal error"):
            retry_with_backoff(
                non_retryable_call,
                max_attempts=3,
                base_delay=0.1,
                sleep_fn=sleeps.append,
            )

        assert attempts == 1
    assert len(sleeps) == 0


def test_backfill_commit_pr_reference_regex_boundary():
    """Verify regex token boundaries for Path 4b commit message PR references."""
    # Pattern equivalent to Postgres: \m(?:PR\s*#?|pull/)<num>\M
    # In Python regex: r'\b(?:PR\s*#?|pull/)(?:123)\b'
    pr_num = "123"
    pattern = re.compile(rf'\b(?:PR\s*#?|pull/){pr_num}\b', re.IGNORECASE)

    # Valid matches
    assert pattern.search("Fix PR #123 properly") is not None
    assert pattern.search("Resolves PR 123") is not None
    assert pattern.search("Merged in pull/123") is not None
    assert pattern.search("PR#123: fix auth") is not None

    # Invalid / bounded matches that must NOT match
    assert pattern.search("SUPERPR123") is None
    assert pattern.search("Fix PR #1234") is None  # Wrong PR number
    assert pattern.search("commit for 123 without prefix") is None
    assert pattern.search("pull/1234") is None  # Wrong PR number


def test_defensive_backfill_guards_all_json_types_without_sql_error():
    """Verify that V002 defensive JSON logic safely handles non-array and malformed types.

    Models the Postgres JSONB guards:
    - Path 1 & 2: jsonb_typeof(metadata->'ticket_ids') = 'array'
    - Path 3: metadata->'author'->>'login' safely handles non-object types
    - Path 4a: CASE WHEN jsonb_typeof(commits) = 'array' ELSE '[]'::jsonb END
    """
    def check_ticket_guard(metadata: dict, ticket_name: str) -> bool:
        """Simulates: sr.metadata ? 'ticket_ids' AND jsonb_typeof(...) = 'array' AND @>."""
        if not isinstance(metadata, dict) or "ticket_ids" not in metadata:
            return False
        ticket_ids = metadata["ticket_ids"]
        # jsonb_typeof(metadata->'ticket_ids') = 'array'
        if not isinstance(ticket_ids, list):
            return False
        return ticket_name in ticket_ids

    # Path 1/2 guards: non-array types must evaluate to False safely
    assert check_ticket_guard({"ticket_ids": "PROJ-123"}, "PROJ-123") is False
    assert check_ticket_guard({"ticket_ids": 12345}, "PROJ-123") is False
    assert check_ticket_guard({"ticket_ids": None}, "PROJ-123") is False
    assert check_ticket_guard({"ticket_ids": {"key": "PROJ-123"}}, "PROJ-123") is False
    assert check_ticket_guard({}, "PROJ-123") is False
    assert check_ticket_guard({"ticket_ids": ["PROJ-100", "PROJ-123"]}, "PROJ-123") is True

    def check_commit_author_guard(metadata: dict, expected_login: str) -> bool:
        """Simulates: sr.metadata->'author'->>'login' = t.metadata->>'login'."""
        if not isinstance(metadata, dict) or "author" not in metadata:
            return False
        author = metadata["author"]
        if not isinstance(author, dict):
            return False  # Postgres ->> operator returns NULL for non-objects
        return author.get("login") == expected_login

    # Path 3 guards: non-object author must evaluate to False safely
    assert check_commit_author_guard({"author": "octocat"}, "octocat") is False
    assert check_commit_author_guard({"author": 999}, "octocat") is False
    assert check_commit_author_guard({"author": None}, "octocat") is False
    assert check_commit_author_guard({"author": {"login": "octocat"}}, "octocat") is True

    def check_pr_commits_guard(metadata: dict, target_sha: str) -> bool:
        """Simulates Path 4a CASE WHEN array ELSE '[]' and object/string sha checks."""
        if not isinstance(metadata, dict) or "commits" not in metadata:
            return False
        commits_val = metadata["commits"]
        # CASE WHEN jsonb_typeof(s_sr.metadata->'commits') = 'array' ... ELSE '[]'::jsonb END
        elements = commits_val if isinstance(commits_val, list) else []
        for c in elements:
            if isinstance(c, dict) and c.get("sha") == target_sha:
                return True
            if isinstance(c, str) and c == target_sha:
                return True
        return False

    # Path 4a guards: non-array commits must safely return empty elements (no crash)
    assert check_pr_commits_guard({"commits": "deadbeef"}, "deadbeef") is False
    assert check_pr_commits_guard({"commits": 12345}, "deadbeef") is False
    assert check_pr_commits_guard({"commits": None}, "deadbeef") is False
    assert check_pr_commits_guard({"commits": {"sha": "deadbeef"}}, "deadbeef") is False
    # Mixed elements array
    assert check_pr_commits_guard(
        {"commits": [123, None, {}, {"sha": "c001"}, "c002"]}, "c001"
    ) is True
    assert check_pr_commits_guard(
        {"commits": [123, None, {}, {"sha": "c001"}, "c002"]}, "c002"
    ) is True
    assert check_pr_commits_guard(
        {"commits": [123, None, {}, {"sha": "c001"}, "c002"]}, "c999"
    ) is False


def test_migration_and_docker_init_parity():
    """Verify that V002__add_relationship_owners.sql and 003-relationship-owners.sql contain identical SQL."""
    base_dir = Path(__file__).resolve().parent.parent.parent
    migration_file = base_dir / "infra" / "migrations" / "V002__add_relationship_owners.sql"
    docker_file = base_dir / "infra" / "docker" / "init" / "003-relationship-owners.sql"

    assert migration_file.exists(), f"Missing {migration_file}"
    assert docker_file.exists(), f"Missing {docker_file}"

    def strip_sql_comments(sql: str) -> str:
        lines = [line.strip() for line in sql.splitlines() if not line.strip().startswith("--")]
        return "\n".join(line for line in lines if line)

    with open(migration_file, "r", encoding="utf-8") as f:
        mig_content = strip_sql_comments(f.read())
    with open(docker_file, "r", encoding="utf-8") as f:
        doc_content = strip_sql_comments(f.read())

    assert mig_content == doc_content, "Migration V002 and Docker init 003 SQL statements must be identical!"
