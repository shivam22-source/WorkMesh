# ADR: Two application services (Java + Python) on PostgreSQL + pgvector

- Status: Superseded by Single Consolidated FastAPI Architecture
- Date: 2026-10-04 (Superseded: 2026-11-04)
- Relates to: AD-01 and AD-02 in the journey's `01_architecture_decisions.md`

## Context

The platform originally handled two categories of work:
1. Enterprise-facing concerns: REST APIs, authentication and user context, role checks, audit logging.
2. AI/ML concerns: connectors, normalization, chunking, dense vector embeddings, hybrid retrieval, graph context reranking, LLM synthesis.

## Historical Decision (Initial Split)

Shipped two deployable application services:
- `backend-java` — Spring Boot API gateway and orchestrator.
- `rag-python` — FastAPI RAG service handling retrieval, indexing, and ML workflows.
- Single unified PostgreSQL + pgvector datastore.

## Superseded Decision: Single Consolidated FastAPI Service

To eliminate inter-service HTTP hop overhead, remove redundant DTO serialization, simplify container orchestration, and deliver an unified deployment footprint, `backend-java` was merged directly into `rag-python` (FastAPI), and `backend-java` was retired.

The single consolidated FastAPI service now directly provides:
1. **Enterprise REST APIs**: `/api/v1/search`, `/api/v1/ask`, `/api/v1/sync/status`, `/api/v1/admin/audit/events`.
2. **User Context & RBAC**: Deterministic user context resolution (`X-User-Id` header handling) with strict ADMIN role checks.
3. **Resilient Audit Trail**: Durable audit event logging to PostgreSQL with fail-open resilience.
4. **Unified Error Contract**: Standard `ApiError` responses (`timestamp`, `status`, `error`, `message`, `path`, `traceId`) across all routes.
5. **Readiness Probe**: `/ready` verifying live PostgreSQL connectivity.
6. **Self-Contained Deployment**: Single container exposing port 8000 and serving the interactive demo console UI.

## Consequences

- **Operational Simplicity**: Exactly one application service to build, test, package, and deploy.
- **Latency Reduction**: Eliminates the inter-service network hop and double-JSON marshaling.
- **Unified Test Suite**: 100% pytest test suite running in < 25s without JVM dependencies.
- **Data Integrity**: Single codebase interfacing with the canonical PostgreSQL + pgvector database.
