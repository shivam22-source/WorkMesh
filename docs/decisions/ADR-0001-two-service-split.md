# ADR: Two application services (Java + Python) on PostgreSQL + pgvector

- Status: Accepted
- Date: 2026-10-04
- Phase: 0
- Relates to: AD-01 and AD-02 in the journey's `01_architecture_decisions.md`

## Context

The platform must do two very different kinds of work:

1. Enterprise-facing concerns — authentication, who is allowed to see what,
   REST APIs, orchestration, audit and admin endpoints.
2. AI/ML concerns — connectors, normalisation, chunking, embeddings, retrieval,
   reranking, relationship extraction, LLM calls, evaluation.

These two areas pull in opposite directions. The enterprise side wants stable,
typed, well-governed APIs with clear permission boundaries. The AI side changes
constantly, depends on Python's ML ecosystem, and needs to be rewritten as
models and retrieval techniques change.

We also need one datastore that stores users, source records, permission
references, chunks, embeddings, sync state, audit events and relationships.

The team is small and this is a six-week build. Every additional deployable is
real operational cost: something to build, version, run, monitor and explain.

## Decision

Ship exactly two deployable application services:

- `backend-java` — Spring Boot. Owns authentication and user context, permission
  decisions, REST APIs, orchestration, audit/admin endpoints, and every call
  into the RAG service.
- `rag-python` — FastAPI. Owns connectors, canonical normalisation, chunking,
  embeddings, retrieval, reranking, relationships, LLM calls and evaluation.

Backend-java talks to rag-python over HTTP through a single narrow interface,
`RagServiceClient`. All contract endpoints live under `/internal/v1/`.

Primary datastore is PostgreSQL with the pgvector extension, using PostgreSQL
full-text search for lexical retrieval and pgvector for embeddings. Redis is not
introduced. Neo4j is not introduced.

Do not split auth, retrieval, audit or connector workers into separate
deployables.

## Alternatives

**Single Spring Boot service doing everything.** Fewer moving parts, but the
RAG code would be JVM/Python-bridge code, which is unpleasant to write and worse
to maintain. It also couples AI iteration cycles to Java release cycles.

**Single Python service doing everything.** Fast to build, and the whole codebase
would be one language. Rejected because the enterprise permission and API
governance layer is the part most likely to be reviewed by a Java/enterprise
team, and that layer is cleaner and more conventional in Spring.

**Many microservices from the start.** Auth service, retrieval service, ingestion
worker, audit service, and so on. Rejected as premature: it multiplies
deployment and debugging surface before there is any scale or team boundary to
justify it.

**OpenSearch or Elasticsearch instead of Postgres.** Better lexical search and
more mature hybrid scoring out of the box. Deferred: it adds a second datastore
to operate before the MVP has proven it needs one. Postgres full-text search plus
pgvector is sufficient for the target corpus.

**Neo4j for the knowledge graph.** Better traversal queries. Deferred per AD-03:
deterministic relationship tables (`entities`, `relationships`) are enough to
demonstrate graph-style context enrichment.

**Redis for caching.** Deferred until a concrete use case exists, per the
architecture contract.

## Why

Two services is the smallest split that gives a clean boundary between the two
halves of the problem. It creates exactly one network boundary, which is one
thing to secure, observe and document — rather than the many that a microservice
split would create.

One datastore keeps the six-week version understandable. The same database holds
the permission references and the chunks, so "can this user see this chunk?" is a
join against data the RAG service already needs, rather than a cross-store
consistency problem.

Keeping auth and permission decisions in Java matches where those decisions
belong organisationally. When a reviewer asks "who decided this employee could
see this document, and where is that enforced?", the answer is a Java class, not
a Python prompt string.

## Consequences

**Easier**

- Permission enforcement has one obvious home, and it is the service an
  enterprise reviewer reads first.
- The AI side can iterate on retrieval and prompts without touching Java.
- Retrieval code has no knowledge of user authentication, so it cannot
  accidentally become a permission bypass path.
- Only two processes to run, which keeps the demo and the runbook short.
- Both services are independently testable: the Java contract test runs with no
  Python process, and the Python tests run with no Java process.

**Harder**

- Data crossing the boundary must be serialised, so contract drift is a real
  failure mode. This is mitigated, not eliminated: both sides have contract
  tests that fail if either side renames a field without the other. Phase 0
  already caught one real drift this way (camelCase versus snake_case).
- Two deployment artefacts instead of one.
- End-to-end debugging needs both log streams correlated; the Python service
  therefore emits structured JSON logs from Phase 0 rather than retrofitting
  them in Phase 6.
- A Java request that depends on Python can fail for two independent reasons
  (Java bug or Python outage). `RagServiceUnavailableException` distinguishes
  the transport failure from a genuine empty result.

**Intentionally deferred**

- Service-to-service authentication. Phase 0 runs the internal contract
  unauthenticated, which is acceptable only because no real or sensitive data
  flows through it yet. A shared token or mTLS **must** exist before any real
  data crosses this boundary.
- Per-call distributed tracing. Log correlation is enough for Phase 0.
- Contract generation from a shared schema file. Hand-written contracts on both
  sides plus paired tests are sufficient at this size; adopt OpenAPI or
  protobuf when the contract grows past a handful of endpoints.
- Dockerfiles for the two services. Phase 0 runs them directly from source.

## Deviations from the original brief

The journey README suggests **Java 25**. This project targets **Java 21 LTS with
Spring Boot 3.5.x**.

Reason: Java 21 is an LTS release with broad adoption, and Spring Boot 3.5.x is a
well-established stable line. Records, sealed types and pattern matching — all
used throughout this codebase because they keep the DTO layer small and readable
— are fully available on Java 21. Choosing Java 25 would have added toolchain
risk without changing anything a reviewer would value. Revisit when Boot 4.x is
settled and a Java 25 runtime is already present in the target environment.