# Public REST API Specification (v1)

Phase 1 introduces the base REST API served by `backend-java`.

All endpoints are rooted under `/api/v1/`.

## Authentication Context

In Phase 1, requests resolve a deterministic local identity:
- **Default user:** `employee_42` (`Alex Engineer`, role: `ENGINEER`, groups: `group_engineering`, `group_backend`)
- **Simulating identities:** pass the `X-User-Id` header (e.g. `X-User-Id: employee_admin`).

---

## 1. POST /api/v1/search

Searches the knowledge base with permission constraints derived from the user's groups.

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
  "totalResults": 0,
  "results": [],
  "searchTimeMs": 12,
  "status": "STUB"
}
```

---

## 2. POST /api/v1/ask

Asks a question and receives an explanation synthesized from permission-filtered evidence.

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

### Response `200 OK`

```json
{
  "question": "why did we change the validation flow?",
  "answer": "Phase 1 stub: Query received for question 'why did we change the validation flow?'. Actual retrieval, permission filtering, and LLM answer synthesis will be active in Phase 4.",
  "citations": [],
  "confidence": "LOW",
  "status": "STUB"
}
```

---

## 3. GET /api/v1/sync/status

Reports the synchronization status and cursor progress across all configured connectors.

### Response `200 OK`

```json
{
  "overallStatus": "IDLE",
  "sources": [
    {
      "sourceType": "GITHUB",
      "status": "IDLE",
      "cursor": null,
      "lastSyncStartedAt": null,
      "lastSyncCompletedAt": null,
      "recordsSyncedLastRun": 0,
      "errorMessage": null
    },
    {
      "sourceType": "SLACK",
      "status": "IDLE",
      "cursor": null,
      "lastSyncStartedAt": null,
      "lastSyncCompletedAt": null,
      "recordsSyncedLastRun": 0,
      "errorMessage": null
    },
    {
      "sourceType": "EMAIL",
      "status": "IDLE",
      "cursor": null,
      "lastSyncStartedAt": null,
      "lastSyncCompletedAt": null,
      "recordsSyncedLastRun": 0,
      "errorMessage": null
    }
  ]
}
```

---

## Error Handling

Validation failures (e.g. blank `query` or `question`) return `400 Bad Request` with the unified `ApiError` body:

```json
{
  "timestamp": "2026-10-30T18:15:00Z",
  "status": 400,
  "error": "Bad Request",
  "message": "query must not be blank",
  "path": "/api/v1/search",
  "traceId": null
}
```
