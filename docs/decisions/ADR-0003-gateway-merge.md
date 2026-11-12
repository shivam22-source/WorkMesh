# ADR-0003: Merging the API Gateway into the RAG Service

- Status: Accepted
- Date: 2026-11-04
- Relates to: [ADR-0001](ADR-0001-single-service-consolidation.md), [ADR-0002](ADR-0002-redis-deferral.md)

## Context

Early project scaffolding separated the user-facing REST API gateway (handling authentication, RBAC checks, and audit logging) from the Python retrieval and RAG engine (`rag-python`). Both services connected to the exact same PostgreSQL + pgvector instance, while the gateway forwarded every search and question-answering request to `rag-python` over HTTP.

## Decision

Merge the API gateway routes, identity verification, RBAC checks, and audit persistence directly into `rag-python` (FastAPI), retiring the separate gateway service permanently.

## Rationale

1. **One Datastore Already Shared:**
   Both tiers read from and wrote to the same PostgreSQL database (users, groups, ACLs, sync state, and audit events). Splitting stateless request handling across two processes added schema duplication without isolating any storage boundary.

2. **Extra Network Hop Gave No Benefit:**
   Routing client traffic through a separate gateway process only to immediately serialize JSON and call `/internal/v1/rag/search` or `/internal/v1/rag/ask` over HTTP added serialization overhead, duplicated DTO validation logic, and required maintaining cross-service contract tests with zero functional upside at current scale.

3. **ACL Pushdown Must Live Next to the DB:**
   WorkMesh enforces permissions inside the SQL retrieval queries (`EXISTS (SELECT 1 FROM acl_references ...)` executed alongside `tsvector` and `pgvector` HNSW scans). Keeping JWT validation, group claim resolution, and SQL query construction in the same FastAPI process ensures the security context is passed directly into the query layer and simplifies end-to-end verification of the SQL security boundary.

## Consequences

- **Positive:** Single deployable container (`rag-python` on port `8000`), unified configuration and observability, and zero inter-service RPC latency.
- **Negative / Trade-off:** CPU-bound sentence-transformer embedding inference shares the FastAPI worker process with API handling; this is mitigated with a bounded concurrency gate (`SEARCH_CONCURRENCY_LIMIT`) and can be scaled horizontally behind a reverse proxy or split into a dedicated embedding worker later if needed.
