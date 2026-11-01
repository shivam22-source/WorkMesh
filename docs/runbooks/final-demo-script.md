# WorkMesh Final Demo Script (8–12 Minutes)

This runbook guides an end-to-end live demonstration of WorkMesh: the enterprise engineering context and grounded RAG platform.

---

## 1. Problem Statement (30–45 sec)

> *"Engineering context is fragmented across Slack discussions, GitHub pull requests and commits, and internal architecture emails. When an incident occurs or an architecture question arises, the rationale is discussed in Slack, coded in GitHub, and communicated over email. WorkMesh unifies these silos with deterministic traceability and pre-LLM permission enforcement."*

---

## 2. Architecture & Security Boundary (60–90 sec)

Highlight the core architectural principles:
- **Dual-Service Separation:**
  - `backend-java` (Spring Boot 3.5, Java 21) acts as the secure API gateway, user identity provider, and audit controller.
  - `rag-python` (FastAPI, Python 3.12) powers connectors, hybrid retrieval, deterministic reranking, and citation synthesis.
- **Security & Authorization Model:**
  - 100% pre-LLM pushdown ACL filtering at the database layer (0% leak rate). The LLM never sees unauthorized chunks.
  - LLM is strictly used for evidence explanation and synthesis, not source access.
  - Admin endpoints (`/api/v1/admin/sync/status`, `/api/v1/admin/audit/events`) require verified `ADMIN` roles.

---

## 3. Step 1: Ingest Multi-Source Fixtures (60 sec)

Run the multi-source ingestion CLI across GitHub, Slack, and Email:

```bash
# Ingest all multi-source synthetic fixtures into PostgreSQL
python -m app.cli.ingest --source all
```

Expected output:
- **GitHub:** 3 records ingested, 4 chunks indexed (PR #123, commits).
- **Slack:** 2 records ingested, 3 chunks indexed (`#payments-engineering` incident thread).
- **Email:** 9 records ingested, 9 chunks indexed (Alex's mailbox, shared finance folders, vendor SLAs).

---

## 4. Step 2: Exact Ticket Identifier Query (60 sec)

Demonstrate exact identifier retrieval linking tickets across systems:

```bash
curl -s -X POST http://localhost:8080/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"query": "DC-8692", "limit": 5}' | jq .
```

Key points to highlight:
- Exact match on ticket identifier `DC-8692`.
- Hybrid retrieval combines lexical full-text search with dense embeddings.
- Returns cross-source hits spanning GitHub PR, Slack discussion, and Email threads.

---

## 5. Step 3: Semantic Grounded Q&A with Citations (90 sec)

Demonstrate grounded RAG answering an engineering rationale question:

```bash
curl -s -X POST http://localhost:8080/api/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"question": "Why did we change the validation flow?"}' | jq .
```

Key points to highlight:
- **Status:** `ANSWERED` with `MEDIUM` confidence.
- **Answer synthesis:** Strictly grounded in numbered evidence chunks. Explains that empty card verification payloads triggered `NullPointerException` (HTTP 500) and were refactored to HTTP 400 Bad Request.
- **Citations:** Every claim contains valid citation links with `sourceType`, `title`, and `url` pointing back to Slack (`p1697364000000100`) and GitHub (`pull/123`).

---

## 6. Step 4: Permission Isolation (Security Boundary) (90 sec)

Demonstrate that confidential evidence is strictly isolated pre-LLM:

### 4A. Authorized Lead Query (Alex Engineer)
```bash
curl -s -X POST http://localhost:8080/api/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"question": "What is the design brief for Project Phoenix?"}' | jq .
```
- **Result:** Successfully answers with citations to `msg-201` (`Confidential Project Phoenix Briefing`).

### 4B. Unauthorized Employee Query (Unprivileged User)
```bash
curl -s -X POST http://localhost:8080/api/v1/ask \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_intern" \
  -d '{"question": "What is the design brief for Project Phoenix?"}' | jq .
```
- **Result:** Status `INSUFFICIENT_EVIDENCE`.
- **Response:** `"I do not have sufficient authorized documentation or evidence to answer this question."`
- **Security Guarantee:** Zero permission leakage. Restricted document never reaches the evidence context or LLM prompt.

---

## 7. Step 5: Cross-Source Entity Traceability (90 sec)

Demonstrate how canonical entities connect engineering assets across platforms:

```bash
curl -s -X POST http://localhost:8080/api/v1/search \
  -H "Content-Type: application/json" \
  -H "X-User-Id: employee_42" \
  -d '{"query": "PaymentValidationService", "limit": 5}' | jq .
```

Highlight the traceability chain:
1. **Jira Issue:** `DC-8692`
2. **Slack Thread:** `p1697364000000100` in `#payments-engineering`
3. **GitHub Pull Request:** `#123` (`Fix null validation in payment card verification`)
4. **Git Commit:** `8af2d1e94b2a8d3e` (`fix(validation): handle empty card verification payloads`)
5. **Email Spec:** `msg-101` (`Validation Flow Refactor for DC-8692`)

---

## 8. Step 6: Admin Sync Status & Audit Trail (60 sec)

Demonstrate administrative observability and role-based access control:

```bash
# Check admin sync status as ADMIN
curl -s -X GET http://localhost:8080/api/v1/admin/sync/status \
  -H "X-User-Id: employee_admin" | jq .

# Verify unprivileged user is rejected (HTTP 403 Forbidden)
curl -s -X GET http://localhost:8080/api/v1/admin/sync/status \
  -H "X-User-Id: employee_42" | jq .

# Inspect durable audit event log as ADMIN
curl -s -X GET http://localhost:8080/api/v1/admin/audit/events \
  -H "X-User-Id: employee_admin" | jq .
```

Key points to highlight:
- Sync status displays per-connector metrics (GitHub, Slack, Email) with cursor timestamps.
- Audit trail logs all search and ask queries with caller identity, timestamp, and query metadata.
- Non-admin attempts fail closed with HTTP 403 Forbidden.

---

## 9. Step 7: Automated Evaluation Benchmark (60 sec)

Execute the evaluation benchmark suite:

```bash
python -m app.cli.benchmark
```

Expected Benchmark Summary:
- **Total Queries:** 10
- **Recall@1:** 80.0%
- **Recall@3:** 100.0%
- **Recall@5:** 100.0%  *(target: >= 85.0%)*
- **Mean Reciprocal Rank (MRR):** 0.9000  *(target: >= 0.60)*
- **Permission Leak Rate:** 0.0%  *(target: 0.0%)*
- **Citation Validity Rate:** 100.0%  *(target: 100.0%)*
- **Mean Latency:** < 5 ms in-memory / < 30 ms PostgreSQL

---

## 10. Closing (30 sec)

> *"WorkMesh demonstrates that enterprise RAG does not require giving LLMs unconstrained access to company data. By enforcing deterministic identity and ACL boundaries before retrieval, grounding generation strictly in numbered evidence chunks, and validating source citations, WorkMesh makes engineering context searchable, traceable, and secure."*
