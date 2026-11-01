"""Automated evaluation benchmark test suite for WorkMesh Phase 6."""

import pytest

from app.evaluation.benchmark import BenchmarkRunner
from app.indexing.repository import InMemoryKnowledgeRepository


@pytest.fixture
def populated_benchmark_runner():
    """Build an in-memory repository populated with all deterministic multi-source fixtures."""
    repo = InMemoryKnowledgeRepository()
    runner = BenchmarkRunner(repository=repo)
    runner.populate_fixtures()
    return runner


def test_evaluation_benchmark_metrics(populated_benchmark_runner):
    """Verify Recall@K, MRR, permission leak rate, and citation validity meet Phase 6 thresholds."""
    runner = populated_benchmark_runner
    summary = runner.run_benchmark()

    # 1. Dataset size and coverage
    assert summary.total_queries == 10, f"Expected 10 benchmark queries, got {summary.total_queries}"

    # 2. Retrieval quality criteria
    assert summary.recall_at_5 >= 0.85, f"Recall@5 ({summary.recall_at_5:.2f}) below 0.85 threshold"
    assert summary.recall_at_3 >= 0.70, f"Recall@3 ({summary.recall_at_3:.2f}) below 0.70 threshold"
    assert summary.mrr >= 0.60, f"MRR ({summary.mrr:.4f}) below 0.60 threshold"

    # 3. Security: Zero permission leak rate
    assert summary.permission_leak_rate == 0.0, (
        f"Permission leak detected! Leak rate: {summary.permission_leak_rate:.4f}"
    )

    # 4. Grounding: 100% valid citations
    assert summary.citation_validity_rate == 1.0, (
        f"Invalid citations detected! Validity rate: {summary.citation_validity_rate:.4f}"
    )

    # 5. Granular case assertions
    for case in summary.case_results:
        assert not case.permission_leak, f"Query '{case.query}' leaked unauthorized documents!"
        if case.query_type == "permission_isolation":
            assert case.hit_at_5, f"Authorized user failed to retrieve document for query '{case.query}'"
            assert not case.permission_leak, f"Unauthorized user accessed restricted document for '{case.query}'"


def test_evaluation_benchmark_json_output(populated_benchmark_runner):
    """Verify benchmark summary serializes cleanly to JSON dictionary."""
    runner = populated_benchmark_runner
    summary = runner.run_benchmark()
    data = summary.to_dict()

    assert "total_queries" in data
    assert "recall_at_5" in data
    assert "mrr" in data
    assert "permission_leak_rate" in data
    assert "citation_validity_rate" in data
    assert "case_results" in data
    assert len(data["case_results"]) == 10
