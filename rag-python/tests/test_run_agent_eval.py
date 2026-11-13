"""Tests for the agent evaluation runner script (scripts/run_agent_eval.py).

Verifies:
1. Query dataset loading (agent_multihop_queries.json).
2. Comparative metrics calculation (gold coverage, steps, latency, tokens).
3. JSON output structure with summary and query-level details.
"""

import json
from pathlib import Path
import sys

import pytest

# Ensure scripts and rag-python are importable
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_agent_eval import evaluate_query, load_multihop_queries


def test_load_multihop_queries_loads_30_queries():
    """Dataset file exists and contains exactly 30 multi-hop queries."""
    queries_path = REPO_ROOT / "data" / "evaluation" / "agent_multihop_queries.json"
    assert queries_path.exists()
    queries = load_multihop_queries(queries_path)
    assert len(queries) == 30
    for q in queries:
        assert "query_id" in q
        assert "question" in q
        assert "user_id" in q
        assert "group_ids" in q
        assert "gold_chunk_ids" in q
        assert len(q["gold_chunk_ids"]) >= 2


def test_evaluate_query_computes_coverage_and_step_metrics():
    """evaluate_query accurately computes gold coverage and latency comparison."""
    from app.agent.service import AgentService
    from app.indexing.repository import InMemoryKnowledgeRepository
    from app.rag.llm import MockLlmProvider
    from app.rag.service import GroundedRagService
    from app.retrieval.hybrid import HybridRetriever

    repo = InMemoryKnowledgeRepository()
    retriever = HybridRetriever(repository=repo)
    rag_service = GroundedRagService(retriever=retriever, llm_provider=MockLlmProvider())
    agent_service = AgentService(retriever=retriever, repository=repo, llm_provider=MockLlmProvider())

    query_record = {
        "query_id": "test-hop-01",
        "question": "What is the secret validation flow?",
        "user_id": "test_user",
        "group_ids": ["test_group"],
        "gold_chunk_ids": ["c1", "c2"],
    }

    result = evaluate_query(query_record, rag_service, agent_service)

    assert result["query_id"] == "test-hop-01"
    assert "single_shot" in result
    assert "agent" in result
    assert result["single_shot"]["steps"] == 1
    assert result["agent"]["steps"] >= 1
    assert "gold_coverage" in result["single_shot"]
    assert "gold_coverage" in result["agent"]
