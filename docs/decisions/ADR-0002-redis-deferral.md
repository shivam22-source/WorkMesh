# ADR: Explicit Deferral of Redis for MVP

- Status: Accepted
- Date: 2026-11-01
- Phase: 5
- Relates to: ADR-0001 (Two application services on PostgreSQL + pgvector)

## Context

During the Phase 5 review of the WorkMesh enterprise knowledge platform, architecture criteria required evaluating whether Redis should be introduced for distributed caching or distributed synchronization in the MVP.

The MVP requirements include:
1. Hybrid retrieval (lexical full-text search and pgvector similarity embeddings).
2. Permission-filtered search and question answering (strict security boundary applied before evidence assembly).
3. Incremental connector synchronization with checkpointing, lease fencing, and replay reconciliation across GitHub, Slack, and Email sources.
4. An immutable audit trail for security-relevant user actions.

## Decision

Explicitly defer introducing Redis for the WorkMesh MVP. Continue to rely on PostgreSQL as the single datastore for all persistence, retrieval, sync coordination, and audit trail needs.

## Rationale

1. **Permission Invariant & Cache Invalidation:**
   In WorkMesh, all retrieval operations are dynamically constrained by the authenticated employee's resolved team group IDs and ACL references in SQL (`chunk.acl_references`). Caching search results or grounded answers in a shared key-value cache by query string introduces significant risk of permission leakage if group memberships or document permissions are updated or revoked. Re-evaluating permissions on each query in PostgreSQL guarantees that no unauthorized document can be retrieved.

2. **Single Datastore Sufficiency:**
   PostgreSQL with full-text search and the pgvector extension currently fulfills all persistence, indexing, and vector similarity search requirements for the MVP corpus without requiring a secondary cache tier.

3. **ACID Connector Lease Fencing:**
   Multi-worker connector synchronization and lease acquisition are implemented directly in PostgreSQL using row-level locking (`SELECT ... FOR UPDATE` and conditional atomic timestamp comparison on the `sync_state` table). This provides transactional consistency and fencing guarantees without the operational complexity of distributed lock managers (such as Redis Redlock).

4. **Operational Simplicity:**
   Introducing Redis would add another infrastructure dependency, connection pool, serialization layer, network failure mode, and monitoring burden without addressing an unmet functional requirement at current scale.

## Consequences

- The architecture maintains a single datastore (`PostgreSQL + pgvector`), avoiding distributed cache invalidation and keeping operations simple.
- Query caching is omitted in favor of consistent, permission-enforced PostgreSQL queries.
- Future re-evaluation: Redis may be revisited post-MVP if measured production profiling demonstrates a concrete bottleneck that cannot be resolved within PostgreSQL, or if cross-node distributed event broadcast becomes necessary.
