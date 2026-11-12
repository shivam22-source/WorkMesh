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

## 2.1 10,000-Chunk Scale & Security Benchmark (`scale_benchmark.py`)

In addition to the 10-query validation set, WorkMesh includes a scale evaluation harness (`python -m app.cli.scale_benchmark --skip-seed`) evaluated against 10,000 indexed chunks (2,500 documents across GitHub, Slack, and Email) and 12,500 multi-tenant ACL rules in PostgreSQL + pgvector:

| Metric | Measured Scale Result | Target | Status | Notes |
|---|---|---|---|---|
| **Evaluated Queries** | **100** (50 exact-ID + 50 semantic) | 100 | PASS | Automated multi-tenant evaluation suite |
| **Recall@1** | **60.0%** | >= 50.0% | PASS | Top candidate matches ground truth target |
| **Recall@5** | **60.0%** | >= 55.0% | PASS | Target present in top 5 fused RRF candidates |
| **Recall@10** | **61.0%** | >= 60.0% | PASS | Target present in top 10 candidates |
| **Mean Reciprocal Rank (MRR)** | **0.6017** | >= 0.5000 | PASS | Evaluated reciprocal rank across full 10k corpus |
| **Cross-Tenant Permission Leaks** | **0 leaks** / 500 queries | 0 | PASS | **0.0% leak rate** across 500 adversarial tests |
| **Adversarial Query Throughput** | **52 ms / query** | < 100 ms | PASS | 500 cross-tenant queries completed in 26.2s |
| **PostgreSQL Index Strategy** | **HNSW (cosine) + GIN (tsvector)** | N/A | PASS | Relational pushdown ACL subqueries |

### 2.2 Retrieval Architecture & Ablation Study
Ablation evaluation across the 100 queries (exact 50/50 split of identifier vs. semantic queries):

| Retrieval Strategy | Exact-ID Queries (50) | Semantic Queries (50) | Overall Recall@5 | Overall MRR |
| :--- | :---: | :---: | :---: | :---: |
| **Lexical Only (`tsvector` / GIN)** | 88.0% | 16.0% | **52.0%** | 0.48 |
| **Vector Only (`pgvector` cosine)** | 24.0% | 60.0% | **42.0%** | 0.38 |
| **Hybrid RRF ($k=60$)** *(Baseline)* | 84.0% | 36.0% | **60.0%** | **0.6017** |
| **Hybrid + Graph Context Reranking** | 90.0% | 58.0% | **74.0%** | **0.7100** |

*Note: With an exact 50/50 query split, Overall Recall@5 is the exact arithmetic mean of both categories (e.g. \((84\% + 36\%) / 2 = 60.0\%\) and \((90\% + 58\%) / 2 = 74.0\%\)).*

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

## 3.1 Graded Multi-Source & Paraphrase Benchmark (`data/evaluation/queries_v2.jsonl`)

While `scale_benchmark.py` exercises 10,000 chunks across 5 recurring template categories, repeated templates cannot isolate semantic paraphrase understanding or cross-source synthesis. To provide an honest, harder retrieval benchmark on top of the 10,000-chunk background corpus, `data/evaluation/queries_v2.jsonl` defines **60 queries** split evenly into 3 categories (`20` each) with **graded relevance (`0–2`)**:

1. **Corpus & Seeding (`app/evaluation/corpus_v2.py`):**
   - Retains all 10,000 synthetic `scale:*` chunks in PostgreSQL as realistic distractor noise and tenant ACL boundaries.
   - Adds 75 distinct domain documents (`77` chunks) across `GITHUB`, `SLACK`, and `EMAIL` covering non-overlapping engineering, security, database, networking, and finance topics, with entity-graph links (`TICKET -> SLACK / PR / COMMIT`) and user/group ACLs.
2. **Graded Relevance (`qrels` on scale `0–2`):**
   - `2`: Primary gold chunk directly answering the query (or for multi-source queries, each of the two primary source chunks required for a complete answer).
   - `1`: Secondary supporting chunk within the same document or follow-up message.
   - `0` (omitted): Non-relevant background chunks.
3. **Query Construction Across 3 Categories (`20 + 20 + 20 = 60`):**
   - **Exact-Identifier (`qv2-id-01` .. `qv2-id-20`)**: 5 unique `DC-10XX` tickets across distinct tenant tiers (`group_engineering`, `group_finance`, `group_security`, user-private `employee_10`) plus 15 unique technical identifiers (commit SHAs, error codes, RPC/class names, Prometheus metrics, CVEs, RFCs, HTTP headers, index names).
   - **Semantic Paraphrases (`qv2-sem-01` .. `qv2-sem-20`)**: Natural-language problem descriptions written deliberately using conceptual synonyms so each query shares **at most 1 content word** (after stopword removal) with any of its gold chunks. Enforced automatically by `scripts/check_overlap.py`.
   - **Multi-Source (`qv2-multi-01` .. `qv2-multi-20`)**: Questions requiring evidence from **two distinct source systems** (e.g., Slack rationale + GitHub PR implementation, or Email approval + Terraform/GitHub change), where both primary source chunks are labeled grade `2`.
4. **User Identities:** Each JSONL record specifies explicit `user_id` and `group_ids` (`employee_42`, `employee_01`, `employee_04`, `employee_05`, `employee_06`, `employee_10`) so ACL pushdown runs realistically per query.
5. **Metrics & Statistical Uncertainty:**
   - **Recall@k** (`k = 1, 3, 5, 10`): Mean per-query fraction of relevant chunks (`grade >= 1`) retrieved in the top `k`.
   - **MRR**: Mean reciprocal rank of the first retrieved chunk with `grade >= 1`.
   - **nDCG@10**: Normalized Discounted Cumulative Gain at cutoff 10 using exponential gains `(2^rel - 1) / log2(rank + 1)` over graded qrels (`0–2`).
   - **Bootstrap 95% CIs**: 2,000 paired query-level bootstrap resamples (`seed=42`) estimating `[2.5%, 97.5%]` confidence intervals for every metric and paired configuration delta.

```bash
# Verify <= 1 content-word overlap on semantic queries (live DB or --offline)
python scripts/check_overlap.py --offline
```

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
