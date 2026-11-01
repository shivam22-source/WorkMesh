# Employee Knowledge RAG (WorkMesh)

Permission-aware enterprise engineering knowledge search and grounded RAG platform: two application services over one PostgreSQL + pgvector datastore.

Built as a 6-phase learning and implementation journey. This repository is at **Phase 6 Complete** — Evaluation, Observability, Hardening, and Final Demo.

---

## Status: Phase 6 (Completed)

| Component | Capabilities & Implementation |
|---|---|
| **`backend-java`** (Spring Boot 3.5, Java 21) | Public REST API gateway (`/api/v1/search`, `/api/v1/ask`, `/api/v1/admin/sync/status`, `/api/v1/admin/audit/events`). Deterministic role-based identity provider (`employee_42`, `employee_admin`). Upfront request validation, admin authorization enforcement, durable PostgreSQL audit logging with fail-safe fallback, robust HTTP RAG client. |
| **`rag-python`** (FastAPI, Python 3.12) | Internal contract API (`/internal/v1/rag/*`). Multi-source connectors (GitHub, Slack, Email), canonical normalizers, source-aware chunkers, mock unit-normalized embeddings, pgvector indexing, pushdown ACL enforcement, relational entity extraction, deterministic reranker, evidence builder, mock extractive LLM, citation extractor. |
| **PostgreSQL 16 + pgvector** | Canonical relational schema (`V001__canonical_schema.sql`): users, groups, source_records, documents, chunks, acl_references, sync_state, audit_events, entities, relationships. HNSW vector indexing + GiST/GIN lexical full-text indexing. |
| **Connectors & Ingestion** | GitHub (PRs, commits, comments), Slack (channels, parent messages, replies), Email (mailboxes, threads, attachments, shared folders). Cursor checkpointing, atomic sync leases, scoped replay reconciliation, retry with exponential backoff. |
| **Hybrid Retrieval & Reranker** | Query classifier (identifier vs semantic), parallel lexical (`tsvector`) + vector (`pgvector`) retrieval with Reciprocal Rank Fusion (RRF), pushdown SQL ACL filtering, candidate-grounded graph entity boost, diversity discounting. |
| **Grounded RAG & Citations** | Structured evidence builder (max 5 items, max 400 chars, no raw graph metadata), offline extractive mock LLM, bracketed citation extraction `[1]`, URL mapping to authoritative source permalinks. |
| **Evaluation Benchmark** | Automated evaluation suite measuring Recall@1, Recall@3, Recall@5, MRR, permission isolation leak rate, citation validity rate, and retrieval latency across 10 curated test queries (`data/evaluation/benchmark_queries.json`). |
| **Observability & Metrics** | Structured timing breakdown across retrieval, rerank, evidence, and LLM stages (`latency_breakdown_ms`). JSON-formatted operational logging and durable audit log trail. |
| **Containerized Demo** | Multi-container Docker Compose demo (`docker-compose.demo.yml`) orchestrating `postgres`, `rag-python`, and `backend-java` with network perimeter isolation. |

Answers are synthesized strictly from permission-filtered retrieved evidence with bracketed citations. Prompt-based access control is never trusted, and ungrounded speculation is prevented by declining to answer (`INSUFFICIENT_EVIDENCE`) when evidence is missing or unauthorized.

---

## Evaluation Benchmark Results

WorkMesh includes an automated benchmark runner (`python -m app.cli.benchmark`) evaluated against the 10-query multi-source benchmark dataset:

| Metric | Target | Actual Result | Status |
|---|---|---|---|
| **Recall@1** | >= 60.0% | **80.0%** | PASS |
| **Recall@3** | >= 70.0% | **100.0%** | PASS |
| **Recall@5** | >= 85.0% | **100.0%** | PASS |
| **Mean Reciprocal Rank (MRR)** | >= 0.6000 | **0.9000** | PASS |
| **Permission Leak Rate** | **0.0%** | **0.0%** (zero leaks) | PASS |
| **Citation Validity Rate** | **100.0%** | **100.0%** (all citations valid) | PASS |
| **Mean Retrieval Latency** | < 50.0 ms | **1.88 ms** (in-memory) / **< 20 ms** (Postgres) | PASS |

---

## Architecture Overview

Two deployable services, one unified PostgreSQL datastore. See [`docs/decisions/ADR-0001-two-service-split.md`](docs/decisions/ADR-0001-two-service-split.md) and [`docs/decisions/ADR-0002-redis-deferral.md`](docs/decisions/ADR-0002-redis-deferral.md).

```mermaid
flowchart TD
    U[Employee / Client] -->|HTTP :8080| J[Spring Boot Gateway<br/>Auth, Role RBAC, Audit]
    J -->|HTTP :8000 /internal/v1| P[FastAPI RAG Engine<br/>Connectors, Hybrid Retrieval, Citations]
    G[External Sources<br/>GitHub, Slack, Email] -->|CLI / Sync| P
    P --> L[Grounded LLM<br/>Evidence-only synthesis]
    P --> D[(PostgreSQL + pgvector<br/>Lexical + Dense Embeddings + ACLs)]
    J --> D
```

---

## Quick Start (Local Run)

Prerequisites: JDK 21+, Python 3.12+, Docker Desktop.

```bash
# 1. Start PostgreSQL + pgvector
docker compose up -d postgres

# 2. Start rag-python (Terminal 1)
cd rag-python
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Start backend-java (Terminal 2)
cd backend-java
./mvnw spring-boot:run

# 4. Ingest multi-source synthetic fixtures
cd rag-python
.venv/Scripts/python.exe -m app.cli.ingest --source all

# 5. Run evaluation benchmark
.venv/Scripts/python.exe -m app.cli.benchmark
```

---

## Full End-to-End Docker Compose Demo

To spin up the entire platform (PostgreSQL, RAG Python engine, and Java API gateway) inside Docker:

```bash
# Start all three services
docker compose -f docker-compose.demo.yml up --build -d

# Verify gateway health
curl http://localhost:8080/actuator/health

# Perform grounded engineering search
curl -s -X POST http://localhost:8080/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"query": "DC-8692"}'

# Perform grounded question answering
curl -s -X POST http://localhost:8080/api/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"question": "Why did we change the validation flow?"}'
```

See [`docs/runbooks/final-demo-script.md`](docs/runbooks/final-demo-script.md) for the complete 8–12 minute live demonstration walkthrough.

---

## Automated Test Suites

All tests run self-contained and offline:

```bash
# Run Java backend JUnit test suite (58 tests)
cd backend-java && ./mvnw test

# Run Python RAG pytest suite (259 tests)
cd rag-python && .venv/Scripts/pytest.exe tests

# Total Automated Tests: 317 passed, 0 failures
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
