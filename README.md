# Employee Knowledge RAG (WorkMesh)

Permission-aware enterprise engineering knowledge search and grounded RAG platform: two application services over one PostgreSQL + pgvector datastore.

Built as a 6-phase learning and implementation journey. This repository is at **Phase 6 Complete** — Evaluation, Observability, Hardening, and Final Demo.

---

## Status: Phase 6 (Completed)

| Component | Capabilities & Implementation |
|---|---|
| **WorkMesh API** (FastAPI, Python 3.12) | Unified REST API (`/api/v1/search`, `/api/v1/ask`, `/api/v1/sync/status`, `/api/v1/admin/audit/events`). Deterministic role-based identity provider (`employee_42`, `employee_admin`), upfront validation, admin RBAC checks, durable PostgreSQL audit logging with fail-safe fallback, multi-source connectors (GitHub, Slack, Email), canonical normalizers, dense embeddings (`sentence-transformers`), pgvector indexing, pushdown ACL enforcement, relational entity extraction, deterministic reranker, evidence builder, grounded LLM synthesis, and citation extractor. |
| **PostgreSQL 16 + pgvector** | Canonical relational schema (`V001__canonical_schema.sql`): users, groups, source_records, documents, chunks, acl_references, sync_state, audit_events, entities, relationships. HNSW vector indexing + GiST/GIN lexical full-text indexing. |
| **Connectors & Ingestion** | GitHub (PRs, commits, comments), Slack (channels, parent messages, replies), Email (mailboxes, threads, attachments, shared folders). Cursor checkpointing, atomic sync leases, scoped replay reconciliation, retry with exponential backoff. |
| **Hybrid Retrieval & Reranker** | Query classifier (identifier vs semantic), parallel lexical (`tsvector`) + vector (`pgvector`) retrieval with Reciprocal Rank Fusion (RRF), pushdown SQL ACL filtering, candidate-grounded graph entity boost, diversity discounting. |
| **Grounded RAG & Citations** | Structured evidence builder (max 5 items, max 400 chars, no raw graph metadata), extractive grounded LLM synthesis, bracketed citation extraction `[1]`, URL mapping to authoritative source permalinks. |
| **Evaluation Benchmark** | Automated evaluation suite measuring Recall@1, Recall@3, Recall@5, MRR, permission isolation leak rate, citation validity rate, and retrieval latency across 10 curated test queries (`data/evaluation/benchmark_queries.json`). |
| **Observability & Metrics** | Structured timing breakdown across retrieval, rerank, evidence, and LLM stages (`latency_breakdown_ms`). JSON-formatted operational logging and durable audit log trail. |
| **Containerized Demo** | Multi-container Docker Compose demo (`docker-compose.demo.yml`) orchestrating `postgres` and `workmesh-api`. |

Answers are synthesized strictly from permission-filtered retrieved evidence with bracketed citations. Prompt-based access control is never trusted, and ungrounded speculation is prevented by declining to answer (`INSUFFICIENT_EVIDENCE`) when evidence is missing or unauthorized.

---

## Evaluation Benchmark & Scale Results

WorkMesh includes two evaluation suites: a curated 10-query validation set and a full 10,000-chunk multi-tenant scale benchmark.

### 1. 10,000-Chunk Scale & Security Benchmark
Evaluated over 10,000 indexed chunks (2,500 documents across GitHub, Slack, and Email) with 12,500 ACL rules over 50 simulated employees and 5 departments in PostgreSQL + pgvector (`python -m app.cli.scale_benchmark --skip-seed`).

*Scale benchmark config: RRF baseline, reranker off.* Raw results: [`data/evaluation/results/scale_benchmark_results.json`](data/evaluation/results/scale_benchmark_results.json).

| Metric | Measured Scale Result | Target | Status |
|---|---|---|---|
| **Recall@1** | **64.0%** | >= 50.0% | PASS |
| **Recall@5** | **72.0%** | >= 55.0% | PASS |
| **Recall@10** | **76.0%** | >= 60.0% | PASS |
| **Mean Reciprocal Rank (MRR)** | **0.6748** | >= 0.5000 | PASS |
| **Cross-Tenant Permission Leak Rate** | **0.0%** (0 leaks / 500 adversarial queries) | 0.0% | PASS |
| **Adversarial Security Throughput** | **147.2 ms / query** (500 queries in 73.6s) | < 200 ms | PASS |

### 2. Retrieval Architecture & Ablation Study
To isolate the contribution of each retrieval stage, an ablation evaluation was performed across an exact 50/50 split of 100 benchmark queries (50 exact-identifier queries vs. 50 semantic natural language queries):

| Retrieval Strategy | Exact-ID Queries (50) | Semantic Queries (50) | Overall Recall@5 | Overall MRR |
| :--- | :---: | :---: | :---: | :---: |
| **Lexical Only (`tsvector` / GIN)** | 100.0% | 20.0% | **60.0%** | 0.6000 |
| **Vector Only (`pgvector` cosine)** | 42.0% | 34.0% | **38.0%** | 0.3062 |
| **Hybrid RRF ($k=60$)** *(Baseline)* | 100.0% | 44.0% | **72.0%** | **0.6748** |
| **Hybrid + Graph Context Reranking** | 100.0% | 50.0% | **75.0%** | **0.6837** |

*Note: With an exact 50/50 query split, Overall Recall@5 is the exact arithmetic mean of the Exact-ID and Semantic categories (e.g. \((100\% + 44\%) / 2 = 72.0\%\) for baseline RRF, and \((100\% + 50\%) / 2 = 75.0\%\) with graph reranking).*

### 3. Limitations & Known Trade-offs
To preserve engineering integrity, the current benchmark methodology recognizes the following constraints:
- **Synthetic Domain Corpus:** The 10,000-chunk scale corpus and benchmark queries originate from the same domain generator; real employee queries introduce typos, conversational ambiguity, and vocabulary mismatch.
- **Dense Embeddings:** Embeddings are generated using the `all-MiniLM-L6-v2` bi-encoder (`sentence-transformers`), zero-padded to 1536 dimensions for `pgvector` index compatibility without modifying schema definitions.
- **Binary Relevance Against Single Target:** Retrieval accuracy is evaluated strictly binary (0 or 1) against a single authoritative target permalink, whereas enterprise queries often feature graded relevance spanning multi-channel threads.
- **Heuristic Graph Boosting:** Entity context boosting uses fixed heuristic weights (+0.15 for linked PRs and tickets) evaluated on the benchmark set rather than a learned cross-encoder model trained on held-out splits.

---

## Architecture Overview

Consolidated single application service on a unified PostgreSQL + pgvector datastore. See [`docs/decisions/ADR-0001-two-service-split.md`](docs/decisions/ADR-0001-two-service-split.md) and [`docs/decisions/ADR-0002-redis-deferral.md`](docs/decisions/ADR-0002-redis-deferral.md).

```mermaid
flowchart TD
    U[Employee / Client] -->|HTTP :8000| A[WorkMesh API (FastAPI)<br/>Auth, Role RBAC, Audit, Search, Q&A]
    G[External Sources<br/>GitHub, Slack, Email] -->|CLI / Sync Workers| A
    A --> L[Grounded LLM<br/>Evidence-only synthesis & bracketed citations]
    A --> D[(PostgreSQL 16 + pgvector<br/>Lexical + Dense Embeddings + ACLs + Audit)]
```

---

## Quick Start (Local Run)

Prerequisites: Python 3.12+, Docker Desktop.

```bash
# 1. Start PostgreSQL + pgvector
docker compose up -d postgres

# 2. Setup and run WorkMesh API
cd rag-python
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Ingest multi-source synthetic fixtures
.venv/Scripts/python.exe -m app.cli.ingest --source all

# 4. Run evaluation benchmark (curated 10 queries)
.venv/Scripts/python.exe -m app.cli.benchmark

# 5. Run 10,000-chunk multi-tenant scale benchmark & ablation study
.venv/Scripts/python.exe -m app.cli.scale_benchmark --skip-seed --ablation

# 6. Live GitHub REST API connector (fetch real PRs & commits)
.venv/Scripts/python.exe -m app.cli.sync_real_github --repo "pallets/flask"
```

---

## Full End-to-End Docker Compose Demo

To spin up the entire platform (PostgreSQL and WorkMesh API service) inside Docker:

```bash
# Start all services
docker compose -f docker-compose.demo.yml up --build -d

# Verify readiness (checks live PostgreSQL connectivity)
curl http://localhost:8000/ready

# Perform grounded engineering search
curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"query": "DC-8692"}'

# Perform grounded question answering
curl -s -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"question": "Why did we change the validation flow?"}'
```

### Interactive Demo Console UI

Once the platform or Docker demo stack is running, open the interactive demo console:
- **Live Platform UI**: [`http://localhost:8000/`](http://localhost:8000/) (served directly from FastAPI static handler).
- **Standalone Offline UI**: Open [`demo-ui/index.html`](demo-ui/index.html) directly in any web browser. Includes an Offline Simulation toggle for presentations without container dependencies, side-by-side ACL leakage audit, Ask AI with grounded citations, and scale/ablation metrics.

See [`docs/runbooks/final-demo-script.md`](docs/runbooks/final-demo-script.md) for the complete 8–12 minute live demonstration walkthrough.

---

## Automated Test Suites

All tests run self-contained and offline:

```bash
# Run pytest test suite (278 tests)
cd rag-python && .venv/Scripts/pytest.exe tests
```

---

## Documentation & Runbooks

| Document | Purpose |
|---|---|
| [`DESIGN.md`](DESIGN.md) | Architectural foundations, scope boundaries, data models, and pushdown ACL invariant |
| [`docs/architecture/overview.md`](docs/architecture/overview.md) | System flows and implementation milestones across all 6 phases |
| [`docs/runbooks/final-demo-script.md`](docs/runbooks/final-demo-script.md) | Step-by-step 8–12 minute demonstration script with exact curl commands |
| [`docs/runbooks/evaluation-and-metrics.md`](docs/runbooks/evaluation-and-metrics.md) | Evaluation benchmark methodology, metrics, and dataset definition |
| [`docs/api/public-rest-api.md`](docs/api/public-rest-api.md) | Public REST endpoints documentation (`/search`, `/ask`, `/admin/*`) |
| [`docs/api/java-python-contract.md`](docs/api/java-python-contract.md) | Wire protocol between backend-java and rag-python |
| [`docs/decisions/ADR-0001-two-service-split.md`](docs/decisions/ADR-0001-two-service-split.md) | Rationale for Java/Python two-service split over unified Postgres |
| [`docs/decisions/ADR-0002-redis-deferral.md`](docs/decisions/ADR-0002-redis-deferral.md) | Architectural justification deferring Redis from the MVP |
