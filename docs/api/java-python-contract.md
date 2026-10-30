# Java → Python Service Contract (v1)

This document specifies the internal wire contract between `backend-java` and `rag-python`.

- Java caller: `com.company.knowledge.orchestrator.ragclient.RagServiceClient`
- Java DTOs: `com.company.knowledge.orchestrator.ragclient.dto`
- Python implementation: `app/api/internal_rag.py`
- Python schema: `app/contracts/rag_health.py`, `app/contracts/rag_search.py`

## Naming rule

The wire format is **camelCase**.

Java records serialise to camelCase by default; Pydantic defaults to snake_case.
Every multi-word field in `app/contracts/` carries an explicit `validation_alias` /
`serialization_alias`.

## Versioning

All internal endpoints live under `/internal/v1/`. A breaking change to any
payload means a new version prefix (`/internal/v2/`) with both versions served
until every caller has moved. Adding an optional field is not a breaking change.

## Endpoints

| Method | Path | Purpose | Auth (Phase 1) |
|---|---|---|---|
| GET | `/health` | Liveness. Process is up. | none |
| GET | `/ready` | Readiness. Process can do real work. | none |
| POST | `/internal/v1/rag/health` | Contract round-trip check. | none |
| POST | `/internal/v1/rag/search` | Search stub carrying identity context. | none |

## POST /internal/v1/rag/health

Request:

```json
{
  "requestedBy": "backend-java",
  "requestedAt": "2026-10-04T12:00:00Z"
}
```

Response `200`:

```json
{
  "status": "ok",
  "service": "rag-python",
  "contractVersion": "v1",
  "message": "contract stub alive"
}
```

## POST /internal/v1/rag/search (Phase 1 Stub)

Carries authenticated employee identity and resolved team group IDs so that
retrieval and ACL filtering can happen before evidence is built.

Request:

```json
{
  "query": "why did we change the validation flow?",
  "userId": "employee_42",
  "groupIds": ["group_engineering", "group_backend"],
  "limit": 10,
  "sourceTypes": ["GITHUB", "SLACK"]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | yes | Search query string. |
| `userId` | string | yes | Authenticated employee identity. |
| `groupIds` | array of strings | yes | Resolved team group IDs for ACL evaluation. |
| `limit` | integer (1..50) | no (default: 10) | Maximum candidate items to retrieve. |
| `sourceTypes` | array of strings | no | Optional filter by source system. |

Response `200`:

```json
{
  "status": "ok",
  "query": "why did we change the validation flow?",
  "totalResults": 0,
  "results": []
}
```

Each result item in `results` (when populated in Phase 3) has the shape:

```json
{
  "chunkId": "chunk_123",
  "documentId": "doc_456",
  "sourceType": "GITHUB",
  "title": "Fix validation flow",
  "snippet": "Updated validation logic in PR #123...",
  "sourceUrl": "https://github.com/company/repo/pull/123",
  "author": "Alex Engineer",
  "score": 0.92
}
```

## Error shape

Both services return the identical error body:

```json
{
  "timestamp": "2026-10-04T12:00:00Z",
  "status": 500,
  "error": "Internal Server Error",
  "message": "unexpected server error",
  "path": "/internal/v1/rag/search",
  "traceId": null
}
```

## Failure handling

| Situation | Python response | Java behaviour |
|---|---|---|
| Service down / DNS fail | connection refused | `RagServiceUnavailableException` → `503 Service Unavailable` |
| Timeout | no response | `RagServiceUnavailableException` → `503 Service Unavailable` |
| Python 5xx | 500 with `ApiError` shape | `RagServiceUnavailableException` → `503 Service Unavailable` |
| Bad request body (4xx) | 422 Unprocessable Entity | `RagClientException` → `500 Internal Server Error` (Java-side bug) |
| Empty 200 body | 200, no body | `RagServiceUnavailableException` → `503 Service Unavailable` |

Timeouts are explicit: 2s connect, 10s read, overridable via
`RAG_CONNECT_TIMEOUT` and `RAG_READ_TIMEOUT`.

## Security status

Unauthenticated in Phase 1 stub mode. S2S token or mTLS is a hard prerequisite for Phase 2 before real data flows.

## Drift protection

Both services carry tests asserting the wire schema:
- `backend-java`: `RestClientRagServiceClientTest`
- `rag-python`: `tests/test_rag_contract.py`
