# Public REST API Specification (v1)

The WorkMesh REST API is served by the consolidated FastAPI service (`rag-python`).

All endpoints are rooted under `/api/v1/`.

## Authentication Context

WorkMesh operates in one of two modes controlled by `AUTH_MODE`:
- **Production Mode (`AUTH_MODE=prod`, default)**: Requests require an `Authorization: Bearer <signed-jwt>` header. Identity, role, and group memberships are extracted from cryptographically verified claims. Simulation headers are rejected.
- **Development Mode (`AUTH_MODE=dev`)**: Resolves identity from simulation headers (`X-User-Id`, `X-User-Role`, `X-User-Groups`), defaulting to `employee_42` (`Alex Engineer`, role: `ENGINEER`, groups: `group_engineering`, `group_backend`).

---

## 1. POST /api/v1/search

Searches the knowledge base with permission constraints derived from the user's groups using hybrid retrieval (tsvector + pgvector RRF).

### Request Body

```json
{
  "query": "why did we change the validation flow?",
  "limit": 10,
  "sourceTypes": ["GITHUB", "SLACK"]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | Cannot be blank. |
| `limit` | integer (1..50) | no | Default: 10. |
| `sourceTypes` | array of strings | no | Optional filter (e.g. `["GITHUB", "SLACK", "EMAIL"]`). |

### Response `200 OK`

```json
{
  "query": "why did we change the validation flow?",
  "totalResults": 1,
  "results": [
    {
      "chunkId": "chunk:github:1",
      "documentId": "doc:github:pr:101",
      "sourceType": "GITHUB",
      "title": "Fix validation flow",
      "snippet": "Updated validation logic in PR #101...",
      "sourceUrl": "https://github.com/company/repo/pull/101",
      "author": "engineer_alice",
      "score": 0.0328
    }
  ],
  "searchTimeMs": 14,
  "status": "SUCCESS"
}
```

---

## 2. POST /api/v1/ask

Asks a question and receives an explanation synthesized strictly from permission-filtered evidence chunks with bracketed citations.

### Request Body

```json
{
  "question": "why did we change the validation flow?",
  "sourceTypes": ["GITHUB"]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `question` | string | yes | Cannot be blank. |
| `sourceTypes` | array of strings | no | Optional filter. |

### Response `200 OK` (Grounded Answer)

```json
{
  "question": "why did we change the validation flow?",
  "answer": "According to the available evidence: empty verification payloads were throwing NullPointerException during checkout, so PaymentValidationService was updated to validate card tokens defensively [1].",
  "citations": [
    {
      "sourceType": "GITHUB",
      "title": "Fix null verification in payment card validation (DC-8692)",
      "url": "https://github.com/company/repo/pull/101",
      "snippet": "Resolves ticket DC-8692: empty verification payloads were throwing NullPointerException..."
    }
  ],
  "confidence": "HIGH",
  "status": "ANSWERED"
}
```

### Response `200 OK` (Insufficient Evidence)

When no permitted evidence or high-relevance chunks are retrieved, the grounded RAG subsystem declines to speculate and returns:

```json
{
  "question": "what is the secret roadmap for 2030?",
  "answer": "I cannot answer this question based on the authorized documents available to you.",
  "citations": [],
  "confidence": "LOW",
  "status": "INSUFFICIENT_EVIDENCE"
}
```

---

## 3. GET /api/v1/sync/status

Reports the synchronization status and cursor progress across all configured connectors. Requires `ADMIN` role.

### Response `200 OK`

```json
{
  "overallStatus": "IDLE",
  "sources": [
    {
      "sourceType": "GITHUB",
      "status": "IDLE",
      "cursor": "cursor_gh_123",
      "lastSyncStartedAt": "2026-11-04T12:00:00Z",
      "lastSyncCompletedAt": "2026-11-04T12:00:05Z",
      "recordsSyncedLastRun": 25,
      "errorMessage": null
    },
    {
      "sourceType": "SLACK",
      "status": "IDLE",
      "cursor": "cursor_sl_456",
      "lastSyncStartedAt": "2026-11-04T12:00:00Z",
      "lastSyncCompletedAt": "2026-11-04T12:00:03Z",
      "recordsSyncedLastRun": 12,
      "errorMessage": null
    },
    {
      "sourceType": "EMAIL",
      "status": "IDLE",
      "cursor": "cursor_em_789",
      "lastSyncStartedAt": "2026-11-04T12:00:00Z",
      "lastSyncCompletedAt": "2026-11-04T12:00:02Z",
      "recordsSyncedLastRun": 8,
      "errorMessage": null
    }
  ]
}
```

---

## Error Handling

Validation failures (e.g. blank `query` or `question`) and all HTTP errors return a uniform JSON error envelope with `code`, `message`, and `request_id` (echoed in `X-Request-Id`):

```json
{
  "error": {
    "code": "BAD_REQUEST",
    "message": "query must not be blank",
    "request_id": "d748f21e5b"
  }
}
```
