# ADR-0001: Single-Service Consolidation (FastAPI on PostgreSQL + pgvector)

- Status: Accepted
- Date: 2026-10-04 (Consolidated: 2026-11-04)
- Relates to: [ADR-0002](ADR-0002-redis-deferral.md), [ADR-0003](ADR-0003-gateway-merge.md)

## Context

The platform handles two tightly coupled categories of work:
1. Request-facing concerns: REST APIs, JWT/dev authentication, user context resolution, RBAC admin checks, and durable audit logging.
2. Retrieval and indexing concerns: connectors, normalization, chunking, dense vector embeddings (`sentence-transformers`), hybrid retrieval (`tsvector` + `pgvector`), graph context reranking, and grounded LLM synthesis.

## Decision

Operate WorkMesh as a **single consolidated FastAPI service (`rag-python`)** backed by a single **PostgreSQL 16 + pgvector** datastore.

The unified FastAPI service directly provides:
1. **Enterprise REST APIs**: `/api/v1/search`, `/api/v1/ask`, `/api/v1/sync/status`, `/api/v1/admin/sync/status`, `/api/v1/admin/sync/reset`, and `/api/v1/admin/audit/events`.
2. **User Context & RBAC**: Fail-closed JWT authentication in production mode (`AUTH_MODE=prod`) and header simulation in dev mode (`AUTH_MODE=dev`), with strict `ADMIN` role enforcement.
3. **Resilient Audit Trail**: Durable audit event logging to PostgreSQL with fail-open resilience so audit write issues do not block user search queries.
4. **Uniform Error Contract**: Structured JSON error responses across all routes with request correlation identifiers.
5. **Health & Readiness Probes**: Separate `/health` (process liveness) and `/ready` (live PostgreSQL connectivity check).
6. **Self-Contained Deployment**: Single container exposing port `8000` and serving the interactive demo UI.

## Consequences

- **Operational Simplicity**: Exactly one application service to build, test, package, and deploy alongside PostgreSQL.
- **Latency Reduction**: Zero inter-service HTTP hops or duplicate JSON marshaling on search and RAG requests.
- **Unified Test Suite**: Self-contained `pytest` suite covering auth, retrieval, ACL pushdown, and API contracts without cross-runtime build complexity.
- **Data Integrity**: Single codebase interfacing directly with the canonical PostgreSQL + pgvector database.
