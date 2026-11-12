# WorkMesh Single-Service Operations & Deployment Guide

This guide covers operational procedures, deployment patterns, configuration options, and observability for the unified WorkMesh Enterprise Knowledge & Context Platform.

---

## 1. System Architecture

WorkMesh operates as a single, consolidated FastAPI application (`rag-python`) backed by PostgreSQL with the `pgvector` extension:

- **Unified API Service**: Consolidated FastAPI service exposing public search (`/api/v1/search`), grounded RAG (`/api/v1/ask`), sync monitoring (`/api/v1/admin/sync/status`), sync lease management (`/api/v1/admin/sync/reset`), and audit logging (`/api/v1/admin/audit/events`).
- **Offline Sentence Transformers**: Local embedding generation via `sentence-transformers/all-MiniLM-L6-v2` with LRU vector caching and offline model loading (`local_files_only=True`).
- **Multi-Tenant ACL Security**: Fail-closed access control enforced at both lexical and vector retrieval stages, supporting deterministic user and group resolution.

---

## 2. Environment Configuration

All settings are configured via environment variables with safe offline defaults:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `WORKMESH_DATABASE_URL` | *(None / In-Memory)* | PostgreSQL connection URL, e.g. `postgresql://workmesh:workmesh@localhost:5432/workmesh`. If unset, an in-memory repository is used for testing. |
| `WORKMESH_EMBEDDING_PROVIDER` | `sentence-transformers` | Embedding provider. Must be `sentence-transformers` or `mock`. Fail-closed if external APIs are unconfigured. |
| `WORKMESH_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Hugging Face model identifier for offline vector embedding. |
| `WORKMESH_EMBEDDING_OFFLINE` | `true` | Enforces offline weight loading without network egress. |
| `WORKMESH_CORS_ORIGINS` | `*` | Comma-separated list of allowed CORS origins (e.g. `http://localhost:3000`). |
| `WORKMESH_LOG_LEVEL` | `INFO` | Standard structured logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

---

## 3. Deployment & Lifecycle

### Step 1: Start PostgreSQL with pgvector

```bash
docker compose up -d postgres
```

Wait until PostgreSQL is healthy:

```bash
docker compose ps
```

### Step 2: Verify Database Schema & pgvector Extension

Run the database verification CLI before starting the application:

```bash
cd rag-python
python -m app.cli.verify_db --require-pgvector
```

Expected exit code is `0` with JSON verification output confirming:
- PostgreSQL connectivity: `true`
- `pgvector` extension installed: `true`
- Core tables (`canonical_documents`, `canonical_chunks`, `source_acls`, `sync_state`, `audit_events`): present

### Step 3: Run the Application

```bash
cd rag-python
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 4. Health Checks & Observability

### Kubernetes Probes

- **Liveness Probe**: `GET /live`
  - Returns `200 OK` if the process is responsive.
- **Readiness Probe**: `GET /ready`
  - Validates live PostgreSQL database connectivity.
  - Returns `200 OK` (`{"status": "READY", "database": "CONNECTED"}`) when healthy.
  - Returns `503 Service Unavailable` if the database is unreachable or pool is exhausted.

### Prometheus Metrics

- **Endpoint**: `GET /metrics`
- Exposes standard Prometheus exposition format:
  - `workmesh_http_requests_total{method="POST", path="/api/v1/search", status="200"}`
  - `workmesh_http_request_duration_seconds_bucket{path="/api/v1/search", le="0.05"}`
  - `workmesh_embedding_cache_hits_total`
  - `workmesh_embedding_cache_misses_total`

### OpenAPI & Interactive Documentation

- **Swagger UI**: `GET http://localhost:8000/docs`
- **ReDoc**: `GET http://localhost:8000/redoc`
- **OpenAPI Schema**: `GET http://localhost:8000/openapi.json`

---

## 5. Operations & Incident Management Runbook

### Incident: Stale Connector Sync Leases

If an ingestion connector worker terminates unexpectedly while holding a lease, the sync state remains marked `RUNNING`.

**Resolution Procedure**:

1. Check current sync status:
   ```bash
   curl -s -H "X-User-Id: employee_admin" http://localhost:8000/api/v1/admin/sync/status | jq .
   ```
2. Reset the affected connector lease (requires `ADMIN` role):
   ```bash
   curl -s -X POST http://localhost:8000/api/v1/admin/sync/reset \
     -H "Content-Type: application/json" \
     -H "X-User-Id: employee_admin" \
     -d '{"sourceType": "GITHUB"}' | jq .
   ```
   Or reset all connectors:
   ```bash
   curl -s -X POST http://localhost:8000/api/v1/admin/sync/reset \
     -H "Content-Type: application/json" \
     -H "X-User-Id: employee_admin" \
     -d '{"sourceType": "ALL"}' | jq .
   ```
3. Verify that connector status has transitioned back to `IDLE` with existing cursors intact.

### Incident: Audit Log Investigation

To retrieve the chronological audit log for security reviews:

```bash
curl -s -H "X-User-Id: employee_admin" \
  "http://localhost:8000/api/v1/admin/audit/events?action=SYNC_RESET&limit=50" | jq .
```
