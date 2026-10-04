# Architecture Overview (Phase 0)

Source of truth: `01_architecture_decisions.md` in the journey package. This file
renders those flows and marks what actually exists.

Legend: `[x]` exists in Phase 0 · `[ ]` planned for a later phase

## The two services

```text
                ┌────────────────────────────────────────────┐
  employee ───▶ │  backend-java  (Spring Boot, :8080)        │
                │                                            │
                │  auth + user context                       │
                │  permission decisions                       │
                │  REST APIs, orchestration                  │
                │  audit + admin endpoints                   │
                └───────────────────┬────────────────────────┘
                                    │  HTTP, /internal/v1  [x] contract stub
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
                │  users, groups [ ]   sources [ ]           │
                │  documents, chunks [ ]  acl refs [ ]       │
                │  sync state [ ]      audit [ ]             │
                │  relationships [ ]                         │
                │  vector extension [x]                      │
                └────────────────────────────────────────────┘
```

## Online query path

```text
[x] Employee
      ▼
[x]   Java Spring Boot API                      backend-java
      ▼
[ ]   Authentication + user context
      ▼
[ ]   Query Orchestrator
      ▼
[x]   ─── HTTP /internal/v1 ───▶ Python RAG service
      ▼
[ ]   Query classification / expansion
      ▼
[ ]   Parallel lexical + vector retrieval
      ▼
[ ]   ACL filtering                ← permission invariant, AD-04
      ▼
[ ]   Relationship enrichment
      ▼
[ ]   Merge / deduplicate
      ▼
[ ]   Rerank
      ▼
[ ]   Evidence builder
      ▼
[ ]   LLM                          ← receives filtered evidence only
      ▼
[ ]   Cited answer
      ▼
[ ]   Java API
      ▼
[x]   Employee
```

Phase 0 implements only the boxes marked `[x]`. The important property to carry
into every later phase: **ACL filtering happens before reranking and before the
LLM**, and the prompt is a second guard, not the security boundary (AD-04).

## Offline ingestion path

```text
[ ] Slack / Email / GitHub
      ▼
[ ]   connector                   AD-07: same interface per source
      ▼
[ ]   incremental change detection (cursor)
      ▼
[ ]   canonical document
      ▼
[ ]   source-aware chunking
      ▼
[ ]   ACL metadata extraction
      ▼
[ ]   embedding
      ▼
[x]   ───────────────▶ PostgreSQL + pgvector
      ▼
[ ]   relationship extraction      AD-03: relational tables, no Neo4j
      ▼
[ ]   sync checkpoint
```

Connector interface every source must expose (AD-07):

```text
authenticate()
list_changes(cursor)
fetch_item(id)
normalize(item)
build_source_link(item)
extract_acl(item)
```

Every connector ships with a real adapter *and* a fixture adapter (AD-08), so
OAuth or rate limits can never block the project.

## What Phase 0 actually is

Phase 0 is deliberately close to empty, on purpose. It establishes:

- both services start and answer a health check;
- one HTTP contract between them, with tests on both sides that fail on drift;
- Postgres with pgvector running locally.

Nothing in the query or ingestion path exists yet. There is no authentication,
no retrieval and no LLM call, and no endpoint exists that could return a
fabricated answer.

## Order of work

```text
Phase 1  canonical schema, user context, API stubs
Phase 2  canonical ingestion + GitHub
Phase 3  hybrid retrieval + Slack
Phase 4  permission enforcement + relationships + RAG
Phase 5  email adapter + incremental sync + admin/audit
Phase 6  evaluation + observability + demo
```

Permission enforcement arrives in Phase 4, but the ACL reference is stored on
every searchable unit from Phase 1 onward. Retrofitting permissions after
indexing real data is the expensive mistake this ordering avoids.