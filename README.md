# WorkMesh

Permission-aware enterprise knowledge search and question answering with verifiable citations.
Powered by a single FastAPI service on PostgreSQL 16 with pgvector.

---

## What WorkMesh Does

- **Hybrid Search**: Combines PostgreSQL full-text search (`tsvector`) with dense vector search (`all-MiniLM-L6-v2` via `pgvector`) using Reciprocal Rank Fusion (RRF).
- **Graph Reranking (Experimental)**: Boosts relevant results based on entity relationships across GitHub pull requests, Slack messages, and internal emails (currently experimental; paired bootstrap testing showed no statistically significant gain on multi-source evaluation).
- **Pushdown Access Control**: Enforces document-level permissions inside PostgreSQL queries so users never see content outside their authorized groups.
- **Grounded Answers**: Extracts supporting citations `[1]` linked to original sources. Declines to answer when evidence is missing or unauthorized.
- **Audit Logging & Admin**: Tracks search and question queries durably with fail-open resilience, plus role-protected connector sync status endpoints.

---

## Real vs. Mocked & Stubbed Components

To ensure complete transparency regarding system capabilities and boundaries:

| Component | Status | Details |
|---|---|---|
| **Embeddings & Vector Index** | **Real** | Local HuggingFace `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dimensions) with PostgreSQL 16 `pgvector` HNSW index. No third-party API keys required. |
| **Lexical Search & Hybrid Fusion** | **Real** | PostgreSQL `tsvector` with GIN indexing, fused with vector search using query-routed Reciprocal Rank Fusion ($k=60$, `hnsw.ef_search=200`). |
| **Cross-Encoder Reranker** | **Optional (`off` by default)** | Optional `cross-encoder/ms-marco-MiniLM-L-6-v2` stage over the top-50 ACL-filtered candidates (`RERANKER=cross_encoder`). Kept off by default because CPU inference increases p95 latency 4.3x (`203.4 -> 870.9 ms`, `+667.5 ms`). |
| **Graph Reranking** | **Experimental** | Candidate-grounded entity relationship boost (`+0.0020` max). Marked experimental because paired bootstrap evaluation on multi-source queries showed `+0.00 pp` Recall@5 and non-significant nDCG@10 (`+0.0102`, `sig=False`). |
| **Pushdown Security & RBAC** | **Real** | SQL-level ACL filtering inside PostgreSQL queries. Production mode enforces signed PyJWT tokens (`sub`, `role`, `groups`) and rejects header simulation. |
| **Concurrency Control & Metrics** | **Real** | Concurrency limiter guards against worker pool starvation, shedding excess load with HTTP 503 (`Retry-After: 1`). Per-stage timings and P95 latency exposed on `/metrics`. |
| **Audit Logging** | **Real** | Transactional database logging with fail-open resilience to prevent user query blocking. |
| **Benchmark Corpus** | **Synthetic** | **Synthetic data**: 10,000 template-generated chunks across 2,500 documents and 12,500 ACL rules. This is not real company data. |
| **LLM Answer Synthesis** | **Stubbed** | Deterministic rule-grounded passage extractor (`MockLLMProvider`). Extracts direct evidence and formats citations without calling a commercial LLM API (such as OpenAI or Anthropic). |
| **Connector Feeds** | **Mocked** | GitHub, Slack, and Email connectors ingest from local JSON fixture files rather than live SaaS OAuth APIs. |

---

## Evaluation Benchmark & Real Ablation Study

Evaluated over 10,000 multi-tenant synthetic chunks (2,500 documents across GitHub, Slack, and Email) with 12,500 ACL rules over 50 simulated users and 5 departments in PostgreSQL + pgvector (`python -m app.cli.scale_benchmark --skip-seed --ablation`).

*The retrieval benchmark and ablation numbers were re-run after the HNSW vector search change.*

### 1. Scale & Security Benchmark

| Metric | Measured Result | Target | Status |
|---|---|---|---|
| **Recall@1** | **63.0%** | >= 50.0% | PASS |
| **Recall@5** | **72.0%** | >= 55.0% | PASS |
| **Recall@10** | **76.0%** | >= 60.0% | PASS |
| **Mean Reciprocal Rank (MRR)** | **0.6681** | >= 0.5000 | PASS |
| **Cross-Tenant Permission Leak Rate** | **0.0%** (0 leaks / 500 adversarial queries) | 0.0% | PASS |
| **Adversarial Security Throughput** | **208.7 ms / query** (500 queries in 104.3s) | < 250 ms | PASS |

Raw results: [`data/evaluation/results/scale_benchmark_results.json`](data/evaluation/results/scale_benchmark_results.json).

### 2. Retrieval Ablation Study

Ablation evaluation across 100 queries (50 exact identifier tickets vs. 50 semantic queries) isolating the impact of each retrieval stage:

| Retrieval Strategy | Exact-ID Queries (50) | Semantic Queries (50) | Overall Recall@5 | Overall MRR |
| :--- | :---: | :---: | :---: | :---: |
| **Lexical Only (`tsvector` / GIN)** | 100.0% | 20.0% | **60.0%** | 0.6000 |
| **Vector Only (`pgvector` cosine)** | 42.0% | 34.0% | **38.0%** | 0.2995 |
| **Hybrid RRF ($k=60$)** *(Baseline)* | 100.0% | 44.0% | **72.0%** | **0.6681** |
| **Hybrid + Graph Context Reranking** | 100.0% | 50.0% | **75.0%** | **0.6753** |

*Note: With an exact 50/50 query split, Overall Recall@5 is the exact arithmetic mean of Exact-ID and Semantic categories (e.g. \((100\% + 44\%) / 2 = 72.0\%\) for baseline RRF, and \((100\% + 50\%) / 2 = 75.0\%\) with graph reranking).*

Raw results: [`data/evaluation/results/ablation_results.json`](data/evaluation/results/ablation_results.json).

### 2b. Harder Graded Evaluation (`queries_v2`, 60 Queries with 95% CIs)

To eliminate lexical keyword leakage, [`data/evaluation/queries_v2.jsonl`](data/evaluation/queries_v2.jsonl) evaluates 60 graded (`0-2`) queries — 20 exact-identifier, 20 low-overlap semantic paraphrases (`<= 1` shared content word with gold chunks, verified via [`scripts/check_overlap.py`](scripts/check_overlap.py)), and 20 multi-source queries — with 95% bootstrap confidence intervals alongside the 10,000-chunk noise corpus:

| Strategy / Configuration | Overall R@5 [95% CI] | Overall MRR | Overall nDCG@10 | ID R@5 | Sem R@5 | Multi R@5 | p50 / p95 ms |
|---|---|:---:|:---:|:---:|:---:|:---:|---:|
| **Hybrid RRF (Before Tuning: `ef=100`, routing off)** | **45.4%** | 0.4875 | 0.4533 | 96.2% | 20.0% | 20.0% | 130.3 / 170.9 |
| **Lexical Only (`tsvector` / GIN)** | 33.3% [21.7%, 45.0%] | 0.3333 | 0.3306 | 100.0% | 0.0% | 0.0% | 39.2 / 62.2 |
| **Vector Only (`limit=10`, `ef=200`)** | 30.0% [20.0%, 41.2%] | 0.3375 | 0.2978 | 50.0% | 20.0% | 20.0% | 91.1 / 141.3 |
| **Hybrid RRF (Tuned Default: `ef=200`, routing on, `RERANKER=off`)** | **74.2%** [62.5%, 84.2%] | **0.7450** | **0.7306** | **100.0%** | **50.0%** | **72.5%** | **180.1 / 203.4** |
| **Hybrid + Graph *(Experimental)*** | 74.2% [62.5%, 84.2%] | 0.7474 | 0.7340 | 100.0% | 50.0% | 72.5% | 206.7 / 251.2 |
| **Hybrid + Cross-Encoder (`RERANKER=cross_encoder`, top-50 ACL pool)** | **75.8%** [64.2%, 85.8%] | **0.7583** | **0.7408** | 100.0% | 50.0% | **77.5%** | 735.9 / 870.9 |

- **Defaults & Latency Decision (`RERANKER=off`)**: Raising `hnsw.ef_search` from `100` to `200` and enabling query-type routing lifts `hybrid_rrf` Recall@5 from `45.4%` to `74.2%` (`+28.8 pp`) and nDCG@10 from `0.4533` to `0.7306`. Enabling `RERANKER=cross_encoder` (`cross-encoder/ms-marco-MiniLM-L-6-v2` over top-50 ACL-filtered candidates) adds `+1.67 pp` R@5 (`77.5%` on multi-source), but regresses CPU `p95` latency **4.3x** (`203.4 ms -> 870.9 ms`), so it stays **off by default**.
- **Experimental Graph Boost**: Paired bootstrap tests across `ablation_v2_results.json` and `reranker_v2_results.json` confirm `+0.00 pp` multi-source Recall@5 delta (`sig=False`) and `+0.0102` nDCG@10 (`95% CI [0.0000, +0.0307]`, `sig=False`), so graph reranking is marked **experimental**.

Raw results & experiment log: [`ablation_v2_results.json`](data/evaluation/results/ablation_v2_results.json), [`sweep_v2_results.json`](data/evaluation/results/sweep_v2_results.json), [`reranker_v2_results.json`](data/evaluation/results/reranker_v2_results.json), and [`docs/experiments.md`](docs/experiments.md).

### 3. Multi-Tenant ACL Recall Verification

Evaluated 30 queries across four tenant permission tiers to assess recall preservation when moving from exhaustive sequential scans to HNSW index retrieval:

| Tenant Access Tier | Accessible Corpus Share | Readable Chunks | Avg Results (Before) | Recall@5 (Before) | Avg Results (After) | Recall@5 (After) | Avg Latency (After) |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| **100% Access** (`test_user_100`) | 100.0% of corpus | 10,000 / 10,000 | 5.00 / 5 | 88.0% | 5.00 / 5 | 88.0% | 4.98 ms |
| **50% Access** (`test_user_50`) | 50.0% of corpus | 5,000 / 10,000 | 5.00 / 5 | 80.0% | 5.00 / 5 | 80.0% | 4.76 ms |
| **10% Access** (`test_user_10`) | 10.0% of corpus | 1,000 / 10,000 | 5.00 / 5 | 80.0% | 5.00 / 5 | 80.0% | 4.55 ms |
| **1% Access** (`test_user_1`) | 1.0% of corpus | 100 / 10,000 | **4.63 / 5** | 80.7% | **5.00 / 5** | **90.7%** | 12.97 ms |

*Before the fix, low-access users ($1\%$) experienced candidate starvation where only 4.63 results on average survived post-filtering. Combining pgvector 0.8 `hnsw.iterative_scan = 'relaxed_order'` with an adaptive exact fallback when surviving rows $< \text{limit}$ restores full 5.00/5 result sets and lifts Recall@5 to 90.7%, with zero permission leakage across all 120 queries.*

### 4. Concurrency Limits & Load Test

WorkMesh protects database and embedding workers from starvation under spike traffic using a concurrency limiter on `/api/v1/search` and `/api/v1/ask`. When the active worker pool is saturated (limit: 15 concurrent queries), the service fails fast with `503 Service Unavailable` and a `Retry-After: 1` header instead of timing out.

Load test executed via Locust (`loadtest/locustfile.py`) across 1 (baseline), 5, 10, 15, 25, 50, and 100 concurrent users against the local server using 52 distinct queries (preventing micro-cache skew). Each run executed for at least 60 seconds after warm-up requests were discarded. All primary benchmark runs used a single identity (`employee_42`, member of `group_engineering` and `group_backend`), with access to **6,000 out of 10,000 chunks (60.0% of the corpus)**. An additional run evaluated 25 concurrent users under a low-access identity (`test_user_1`, access to **100 out of 10,000 chunks / 1.0% of the corpus**). Latencies report exclusively on successful requests:

| Concurrency Level & Identity | Total Requests | Successful (2xx) | 503 Backpressure Shed | Other Errors | P50 Latency (Success) | P95 Latency (Success) | Throughput (Success) |
|---|---|---|---|---|---|---|---|
| **1 User** (baseline, `employee_42`, 60% access) | 218 | 218 | 0 | 0 | **110.0 ms** | **230.0 ms** | 3.75 req/s |
| **5 Users** (`employee_42`, 60% access) | 1,012 | 1,012 | 0 | 0 | **120.0 ms** | **320.0 ms** | 17.36 req/s |
| **10 Users** (`employee_42`, 60% access) | 1,777 | 1,777 | 0 | 0 | **160.0 ms** | **520.0 ms** | 29.89 req/s |
| **15 Users** (`employee_42`, 60% access) | 2,285 | 2,282 | 3 | 0 | **210.0 ms** | **640.0 ms** | 38.37 req/s |
| **25 Users** (`employee_42`, 60% access) | 3,351 | 2,147 | 1,204 | 0 | **380.0 ms** | **1,100.0 ms** | 36.16 req/s |
| **50 Users** (`employee_42`, 60% access) | 4,424 | 1,802 | 2,622 | 0 | **760.0 ms** | **1,400.0 ms** | 30.35 req/s |
| **100 Users** (`employee_42`, 60% access) | 4,595 | 1,729 | 2,866 | 0 | **1,400.0 ms** | **2,400.0 ms** | 29.04 req/s |
| **25 Users (Low Access)** (`test_user_1`, 1% access) | 1,990 | 582 | 1,408 | 0 | **780.0 ms** | **1,500.0 ms** | 9.97 req/s |

**Environment & Setup:**
- **Machine**: 13th Gen Intel(R) Core(TM) i5-13500HX (14 cores, 20 logical threads), 16 GB RAM, Windows 11.
- **Topology**: FastAPI application (`127.0.0.1:8000`) and PostgreSQL 16 + pgvector container ran on the same physical host machine.
- **Embedding Provider**: Local HuggingFace `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dimensions) running on CPU.
- **Concurrency Limit**: 15 concurrent queries (`SEARCH_CONCURRENCY_LIMIT=15`).
- **Query Pool**: 52 distinct queries covering Jira tickets, architectural questions, operational scenarios, and multi-source connector concepts.

Before optimization, PostgreSQL vector queries bypassed the HNSW index due to correlated multi-table ACL pushdown joins, resulting in 52.48 million row nested-loop semi-joins taking ~3.9 seconds per query. By retrieving top nearest-neighbor candidate chunks directly via the HNSW index (`idx_chunks_embedding_hnsw` with `ef_search=100`) and evaluating pushdown ACLs on candidate chunks with iterative scan fallback when fewer candidates survive, vector search latency dropped from ~3,920 ms to ~28 ms.

The application handles up to 15 concurrent users without backpressure shedding, processing up to 38.4 successful requests/second with p95 latency under 640 ms for standard users. Beyond 15 concurrent users, the concurrency limiter sheds excess traffic with immediate HTTP 503 responses (~20–300 ms), keeping database connections healthy while sustaining 29–36 successful req/sec. For low-access users (1% access), exact fallback with iterative scan preserves full Recall@5 (90.67%) with zero unauthorized chunk leakage, sustaining 9.97 successful req/sec at 25 concurrent users.

---

## Architecture

A single consolidated FastAPI application interfacing directly with PostgreSQL 16 + pgvector. See [`docs/decisions/ADR-0001-two-service-split.md`](docs/decisions/ADR-0001-two-service-split.md).

```mermaid
flowchart TD
    U["Employee / Web Client"] -->|"HTTP :8000"| A["WorkMesh API (FastAPI)<br/>Auth, RBAC, Search, Q&A, Audit"]
    G["External Sources<br/>GitHub, Slack, Email"] -->|"CLI / Sync Workers"| A
    A --> L["Grounded LLM<br/>Evidence synthesis & citations"]
    A --> D[("PostgreSQL 16 + pgvector<br/>Lexical + Dense Embeddings + ACLs + Audit")]
```

---

## Quick Start

### Authentication Modes

WorkMesh supports two runtime authentication modes controlled by `AUTH_MODE`:

- **Production Mode (`AUTH_MODE=prod`, default)**: Strict fail-closed JWT authentication. Every request must supply a valid `Authorization: Bearer <token>` signed with `JWT_SECRET`. Identity, role, and group memberships are extracted exclusively from verified claims (`sub`, `role`, `groups`). Simulation headers (`X-User-Id`, `X-User-Role`, `X-User-Groups`) are rejected with `401 Unauthorized`.
- **Development Mode (`AUTH_MODE=dev`)**: Allows header-based identity simulation for testing and local demos. A warning is logged on startup. **Dev mode is not safe for production.**

Tokens are issued outside this service; WorkMesh expects and validates the claims `sub` (user ID), `role` (user role), `groups` (authorized group list), and `exp` (token expiration).

### 1. Run with Docker Compose

```bash
# Start PostgreSQL and the WorkMesh API
docker compose -f docker-compose.demo.yml up --build -d

# Verify readiness (checks live database connection)
curl http://localhost:8000/ready

# Search enterprise knowledge (dev mode)
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"query": "DC-8692"}'

# Ask a grounded question (dev mode)
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"question": "Why did we change the validation flow?"}'
```

### 2. Interactive Web UI

- **Live UI**: Open [`http://localhost:8000/`](http://localhost:8000/) in your browser while the service is running.
- **Offline UI**: Open [`demo-ui/index.html`](demo-ui/index.html) directly in any browser with the offline simulation toggle.

### 3. Local Development

```bash
# Start database
docker compose up -d postgres

# Install Python dependencies and start API
cd rag-python
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Ingest synthetic documents
.venv/Scripts/python.exe -m app.cli.ingest --source all

# Run 10,000-chunk scale benchmark & ablation study
.venv/Scripts/python.exe -m app.cli.scale_benchmark --skip-seed --ablation
```

---

## Tests

The test suite runs self-contained and offline:

```bash
cd rag-python
.venv/Scripts/pytest.exe tests
```

344 passed with model weights cached (or 340 passed and 4 deselected with `-m "not real_model"` when skipping `@pytest.mark.real_model` tests without cached weights). Covers hybrid retrieval, query-type routing, optional Cross-Encoder reranking, pushdown ACL enforcement, grounded answer synthesis, citation validation, role-based access control, concurrency backpressure, and error handling contracts.

---

## Documentation

- [`DESIGN.md`](DESIGN.md): System architecture, data model, and pushdown ACL invariant.
- [`docs/runbooks/final-demo-script.md`](docs/runbooks/final-demo-script.md): Live walkthrough script with example queries.
- [`docs/runbooks/evaluation-and-metrics.md`](docs/runbooks/evaluation-and-metrics.md): Evaluation methodology and metrics definitions.
- [`docs/experiments.md`](docs/experiments.md): Semantic weakness sweeps, Cross-Encoder latency/recall benchmarks, and experimental graph boost findings.
- [`docs/decisions/ADR-0001-two-service-split.md`](docs/decisions/ADR-0001-two-service-split.md): Consolidation rationale to single FastAPI service.
- [`docs/decisions/ADR-0002-redis-deferral.md`](docs/decisions/ADR-0002-redis-deferral.md): Datastore simplicity and Redis deferral rationale.
