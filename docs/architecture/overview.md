# Architecture Overview (Phase 6 Complete)

Source of truth: `01_architecture_decisions.md` in the journey package. This file
renders those flows and confirms that all components are fully implemented and verified.

Legend: `[x]` verified complete across Phases 1–6

## The two services

```text
                ┌────────────────────────────────────────────┐
  employee ───▶ │  backend-java  (Spring Boot 3.5, Java 21) │
                │                                            │
                │  auth + user context [x]                   │
                │  admin role verification [x]               │
                │  REST APIs & orchestration [x]             │
                │  durable audit persistence [x]             │
                │  admin sync & audit endpoints [x]          │
                └───────────────────┬────────────────────────┘
                                    │  HTTP, /internal/v1 [x] wire contracts
                                    ▼
                ┌────────────────────────────────────────────┐
                │  rag-python  (FastAPI, Python 3.12)        │
                │                                            │
                │  connectors [x] (GitHub, Slack, Email)     │
                │  normalization [x]  chunking [x]           │
                │  embeddings [x]     hybrid retrieval [x]   │
                │  reranking [x]      relationships [x]      │
                │  grounded LLM [x]   citations [x]          │
                │  evaluation & benchmark [x]                │
                └───────────────────┬────────────────────────┘
                                    │
                                    ▼
                ┌────────────────────────────────────────────┐
                │  PostgreSQL 16 + pgvector                  │
                │  users, groups [x]   sources [x]           │
                │  documents, chunks [x]  acl refs [x]       │
                │  sync state [x]      audit logs [x]        │
                │  relationships [x]   vector extension [x]  │
                └────────────────────────────────────────────┘
```

## Online query path

```text
[x] Employee
      ▼
[x]   Java Spring Boot API                      backend-java (/api/v1/search, /api/v1/ask)
      ▼
[x]   Authentication + user context             (Role-aware deterministic identity provider)
      ▼
[x]   Query Orchestrator                        (SearchServiceImpl orchestrating RAG client)
      ▼
[x]   ─── HTTP /internal/v1 ───▶ Python RAG service (POST /internal/v1/rag/search, POST /internal/v1/rag/ask)
      ▼
[x]   Query classification / expansion         (Identifier vs semantic query classification)
      ▼
[x]   Parallel lexical + vector retrieval       (PostgreSQL tsvector + pgvector dense cosine)
      ▼
[x]   Pre-LLM Pushdown ACL filtering            (AD-04: strict SQL security boundary, 0% leak rate)
      ▼
[x]   Relationship enrichment                   (AD-03: candidate-grounded relational graph boost)
      ▼
[x]   Merge / deduplicate                       (Reciprocal Rank Fusion - RRF)
      ▼
[x]   Deterministic Rerank                      (Token bonuses, graph boosts, source diversity)
      ▼
[x]   Evidence builder                          (Numbered context, max 5 items, max 400 chars)
      ▼
[x]   LLM synthesis                             (Evidence-only extraction prompt, no hallucinations)
      ▼
[x]   Citation extraction & validation          (Structured citations mapping claims to source URLs)
      ▼
[x]   Durable Audit Logging                     (PostgreSQL audit persistence with SLF4J fallback)
      ▼
[x]   Java API Response                         (Clean AskResponse with status, answer, citations)
      ▼
[x]   Employee
```

## Offline ingestion path

```text
[x] Sources: GitHub [x] · Slack [x] · Email [x]
      ▼
[x]   connector                   AD-07: unified SourceConnector (fixtures + live adapters)
      ▼
[x]   incremental sync & leases   (Atomic sync lease fencing, cursor checkpoint in sync_state)
      ▼
[x]   canonical document          (Normalizers -> CanonicalDocument with stable metadata)
      ▼
[x]   source-aware chunking       (SourceAwareChunker -> CanonicalChunk with deterministic SHA-256)
      ▼
[x]   ACL metadata extraction     (Explicit user IDs, group IDs, inherited permissions)
      ▼
[x]   embedding                   (EmbeddingProvider -> MockEmbeddingProvider, unit-normalized)
      ▼
[x]   ───────────────▶ PostgreSQL + pgvector (Transactional batch upsert with cursor update)
      ▼
[x]   relationship extraction     AD-03: relational tables, cross-system entity links
      ▼
[x]   sync checkpoint             (SyncStateRecord: SUCCESS/FAILED with retryable cursor)
```

## Implementation Milestones

```text
Phase 1  canonical schema, user context, API stubs                [COMPLETED]
Phase 2  canonical ingestion + GitHub connector                   [COMPLETED]
Phase 3  hybrid retrieval + Slack connector                       [COMPLETED]
Phase 4  permission enforcement + relationships + Grounded RAG    [COMPLETED]
Phase 5  email adapter + incremental sync + admin sync & audit    [COMPLETED]
Phase 6  evaluation benchmark + observability + docker demo       [COMPLETED]
```
