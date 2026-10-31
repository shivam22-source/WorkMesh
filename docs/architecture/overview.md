# Architecture Overview (Phase 1)

Source of truth: `01_architecture_decisions.md` in the journey package. This file
renders those flows and marks what actually exists.

Legend: `[x]` exists in Phase 1 · `[ ]` planned for a later phase

## The two services

```text
                ┌────────────────────────────────────────────┐
  employee ───▶ │  backend-java  (Spring Boot, :8080)        │
                │                                            │
                │  auth + user context [x] (stub)            │
                │  permission decisions [ ]                  │
                │  REST APIs, orchestration [x] (stubs)      │
                │  audit + admin endpoints [x] (stubs)       │
                └───────────────────┬────────────────────────┘
                                    │  HTTP, /internal/v1  [x] contract stubs (health, search)
                                    ▼
                ┌────────────────────────────────────────────┐
                │  rag-python  (FastAPI, :8000)              │
                │                                            │
                │  connectors [ ]   normalization [ ]        │
                │  chunking [ ]      embeddings [ ]          │
                │  retrieval [ ]     reranking [ ]           │
                │  relationships [ ] LLM [ ]                 │
                │  evaluation [ ]                            │
                └───────────────────┬────────────────────────┘
                                    │
                                    ▼
                ┌────────────────────────────────────────────┐
                │  PostgreSQL + pgvector                     │
                │  users, groups [x]   sources [x]           │
                │  documents, chunks [x]  acl refs [x]       │
                │  sync state [x]      audit [x]             │
                │  relationships [x]                         │
                │  vector extension [x]                      │
                └────────────────────────────────────────────┘
```

## Online query path

```text
[x] Employee
      ▼
[x]   Java Spring Boot API                      backend-java (/api/v1/search, /api/v1/ask)
      ▼
[x]   Authentication + user context             (Phase 1 deterministic local context)
      ▼
[x]   Query Orchestrator                        (SearchService base orchestrator)
      ▼
[x]   ─── HTTP /internal/v1 ───▶ Python RAG service (POST /internal/v1/rag/search, POST /internal/v1/rag/ask)
      ▼
[x]   Query classification / expansion
      ▼
[x]   Parallel lexical + vector retrieval
      ▼
[x]   ACL filtering                ← permission invariant, AD-04
      ▼
[x]   Relationship enrichment
      ▼
[x]   Merge / deduplicate
      ▼
[x]   Rerank
      ▼
[x]   Evidence builder
      ▼
[x]   LLM                          ← receives filtered evidence only
      ▼
[x]   Cited answer
      ▼
[x]   Java API
      ▼
[x]   Employee
```

## Offline ingestion path

```text
[x] GitHub [x] (Slack / Email [ ])
      ▼
[x]   connector                   AD-07: same interface per source (GitHubFixtureAdapter, GitHubApiAdapter)
      ▼
[x]   incremental change detection (cursor checkpoint in sync_state)
      ▼
[x]   canonical document          (GitHubNormalizer -> CanonicalDocument)
      ▼
[x]   source-aware chunking       (SourceAwareChunker -> CanonicalChunk with stable IDs & SHA-256)
      ▼
[x]   ACL metadata extraction     (inherited per chunk and resource)
      ▼
[x]   embedding                   (EmbeddingProvider -> MockEmbeddingProvider, unit-normalized)
      ▼
[x]   ───────────────▶ PostgreSQL + pgvector (schema initialized & indexed)
      ▼
[x]   relationship extraction      AD-03: relational tables, no Neo4j
      ▼
[x]   sync checkpoint             (SyncStateRecord: SUCCESS/FAILED with retryable cursor)
```

## Order of work

```text
Phase 1  canonical schema, user context, API stubs  [COMPLETED]
Phase 2  canonical ingestion + GitHub               [COMPLETED]
Phase 3  hybrid retrieval + Slack                   [COMPLETED]
Phase 4  permission enforcement + relationships + RAG [COMPLETED]
Phase 5  email adapter + incremental sync + admin/audit
Phase 6  evaluation + observability + demo
```
