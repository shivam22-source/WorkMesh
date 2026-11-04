# Architecture Overview

This document describes the unified system architecture and component flows of WorkMesh.

## Unified Service Architecture

```text
                ┌────────────────────────────────────────────┐
  employee ───▶ │  WorkMesh API Service (FastAPI, Python)    │
                │                                            │
                │  auth + user context (JWT / dev header)    │
                │  admin role verification & sync leases     │
                │  REST endpoints (/api/v1/search, /ask)     │
                │  durable audit persistence                 │
                │  connectors (GitHub, Slack, Email)         │
                │  normalization & source-aware chunking     │
                │  sentence-transformers embeddings (384-dim)│
                │  hybrid retrieval (tsvector + pgvector)    │
                │  candidate-grounded graph reranking        │
                │  grounded LLM synthesis & citations        │
                │  evaluation & benchmark harness            │
                └───────────────────┬────────────────────────┘
                                    │  psycopg + pgvector
                                    ▼
                ┌────────────────────────────────────────────┐
                │  PostgreSQL 16 + pgvector                  │
                │  users, groups, user_group_membership      │
                │  documents, chunks (vector 384)            │
                │  acl_references (pushdown SQL security)    │
                │  entities, relationships (graph metadata)  │
                │  sync_state, audit_events                  │
                └────────────────────────────────────────────┘
```

## Online Query Path

```text
Employee
  ▼
FastAPI API Gateway (/api/v1/search, /api/v1/ask)
  ▼
Authentication & Identity Resolution (JWT verification / dev headers)
  ▼
Query Classification (Identifier, keyword, semantic, or mixed)
  ▼
Parallel Lexical + Vector Retrieval (tsvector @@ query + pgvector <=> cosine)
  ▼
Pushdown ACL Enforcement (SQL EXISTS check against authorized groups)
  ▼
Reciprocal Rank Fusion (RRF, k=60 combining lexical + vector candidates)
  ▼
Candidate-Grounded Graph Reranking (Entity neighbor boosts + diversity discounting)
  ▼
Evidence Set Construction (Permission-filtered chunks, max 5 items)
  ▼
Grounded Answer Synthesis (Strict evidence-only extraction prompt)
  ▼
Citation Extraction & Verification (Claims mapped to source URLs [1])
  ▼
Durable Audit Logging (PostgreSQL audit log with fail-open fallback)
  ▼
API Response (Formatted JSON with status, answer, citations, searchTimeMs)
  ▼
Employee
```

## Offline Ingestion Path

```text
Sources: GitHub · Slack · Email
  ▼
Source Connectors (Fixtures and live API adapters)
  ▼
Incremental Sync & Leases (Atomic sync lease fencing, cursor checkpoints in sync_state)
  ▼
Canonical Normalization (Platform-specific payloads -> CanonicalDocument)
  ▼
Source-Aware Chunking (Markdown/code/email chunkers -> CanonicalChunk with SHA-256 hash)
  ▼
ACL Extraction (Document-level and chunk-level permissions mapped to principal IDs)
  ▼
Vector Embedding (sentence-transformers/all-MiniLM-L6-v2 -> 384 dimensions)
  ▼
Transactional Write (PostgreSQL documents, chunks, vectors, ACLs, and sync state)
  ▼
Entity & Relationship Extraction (TICKET -> THREAD -> PR -> COMMIT -> EMPLOYEE)
```
