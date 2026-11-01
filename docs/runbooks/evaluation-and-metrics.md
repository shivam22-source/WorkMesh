# Evaluation & Observability Runbook

This document details the evaluation methodology, quality benchmarks, security metrics, and latency observability in WorkMesh.

---

## 1. Overview & Objectives

In enterprise engineering search, standard conversational evaluation is insufficient. Retrieval must satisfy four hard engineering criteria:
1. **High Precision on Identifiers & Code Terms:** Exact ticket IDs (e.g. `DC-8692`), commits, and method names must rank at top positions.
2. **Semantic Recall Across Silos:** Natural language rationale queries (e.g. *"why did we change validation?"*) must connect discussion in Slack with code in GitHub.
3. **Zero Permission Leakage (100% Security Isolation):** Unauthorized employees must have a 0.0% leak rate on restricted private items.
4. **Verifiable Grounding:** Every factual answer claim must cite a valid source URL from retrieved evidence.

---

## 2. Core Retrieval & Grounding Metrics

| Metric | Target | Actual (Phase 6) | Description |
|---|---|---|---|
| **Recall@1** | >= 60.0% | **80.0%** | Fraction of queries where the authoritative source is the #1 hit |
| **Recall@3** | >= 70.0% | **100.0%** | Fraction of queries where an authoritative source is in the top 3 hits |
| **Recall@5** | >= 85.0% | **100.0%** | Fraction of queries where an authoritative source is in the top 5 hits |
| **Mean Reciprocal Rank (MRR)** | >= 0.6000 | **0.9000** | Average of reciprocal rank of the first relevant document (\(1 / \text{rank}\)) |
| **Permission Leak Rate** | **0.0%** | **0.0%** | Percentage of queries where an unauthorized user retrieves private data |
| **Citation Validity Rate** | **100.0%** | **100.0%** | Percentage of citations with valid URL and matching evidence content |

---

## 3. Evaluation Dataset (`data/evaluation/benchmark_queries.json`)

The benchmark dataset consists of 10 curated test cases across 4 distinct categories:

1. **Identifier Queries:**
   - `eval-001` (`DC-8692`): Exact Jira ticket identifier linking Slack, GitHub PR, and Email thread.
   - `eval-002` (`commit 8af2d1e94b2a8d3e`): Exact Git commit SHA.
   - `eval-003` (`PaymentValidationService`): Exact code class identifier.
2. **Semantic Incident & Rationale Queries:**
   - `eval-004` (`why did we change the validation flow?`): Semantic rationale query explaining why empty card verification payloads were changed from HTTP 500 to 400.
   - `eval-005` (`checkout validation error NullPointerException`): Incident diagnosis query matching stack traces and discussion.
   - `eval-010` (`External Vendor SLA Update`): Semantic query matching cloud maintenance notice.
3. **Cross-Source Synthesis Queries:**
   - `eval-006` (`show discussion and implementation DC-8692`): Synthesis connecting Slack discussion with GitHub implementation.
   - `eval-007` (`Validation Flow Refactor for DC-8692`): Cross-source query linking email architecture discussion to Slack/GitHub.
4. **Permission Isolation Test Queries:**
   - `eval-008` (`Confidential Project Phoenix Briefing`): Private email brief accessible to Alex Engineer (`employee_42`), strictly withheld from unauthorized user (`unauthorized_user_99`).
   - `eval-009` (`Q3 Departmental Financial Summary`): Shared folder email requiring `group_finance` membership; unauthorized user receives zero results.

---

## 4. Latency Breakdown & Observability

Every Grounded RAG request (`/api/v1/ask` and `/internal/v1/rag/ask`) records structured timing breakdown metrics:

```json
{
  "latencyBreakdownMs": {
    "retrieval_ms": 1.84,
    "rerank_ms": 0.24,
    "evidence_ms": 0.04,
    "llm_ms": 0.23,
    "total_ms": 2.41
  }
}
```

### Stage Definitions:
- **`retrieval_ms`:** Hybrid execution combining PostgreSQL full-text search (`tsvector`), dense pgvector embedding similarity, and Reciprocal Rank Fusion (RRF) with pushdown ACL filters.
- **`rerank_ms`:** Deterministic reranking applying exact token matches, candidate-grounded graph entity boosts, and source diversity penalties.
- **`evidence_ms`:** Construction of the structured numbered evidence block (capped at 5 items and 400 characters per item, stripping internal graph metadata).
- **`llm_ms`:** Extraction synthesis using the mock LLM provider, followed by citation parsing and URL mapping.
- **`total_ms`:** End-to-end processing latency.

### Structured Logging:
Both services emit JSON-formatted logs for structured observability:
```json
{"ts":"2026-11-01 17:25:49,553","level":"INFO","message":"grounded_rag_ask_completed user_id=employee_42 status=ANSWERED total_ms=2.41 citations=5 breakdown={'retrieval_ms': 1.84, 'rerank_ms': 0.24, 'evidence_ms': 0.04, 'llm_ms': 0.23, 'total_ms': 2.41}"}
```

---

## 5. How to Run the Benchmark

### In-Memory Benchmark (Fast Test Suite)
```bash
cd rag-python
python -m app.cli.benchmark
```

### PostgreSQL Benchmark (Live Database)
```bash
cd rag-python
python -m app.cli.benchmark --postgres
```

### Raw JSON Output (For CI/CD Automation)
```bash
python -m app.cli.benchmark --json
```

### Automated Pytest Suite
```bash
pytest rag-python/tests/test_evaluation_benchmark.py -v
```
