# WorkMesh API & Service Contract (v1)

This document specifies the unified API and data contracts served by the consolidated WorkMesh FastAPI service (`rag-python`).

- Service Implementation: `app/main.py`, `app/api/public_v1.py`, `app/api/internal_rag.py`
- Contract Models: `app/contracts/`
- Authentication & Identity: `app/auth/user_context.py`

## Naming Convention

The wire format for JSON payloads is **camelCase**. Every multi-word field in `app/contracts/` and `app/api/` carries explicit aliases (`validation_alias` / `serialization_alias`) ensuring consistent camelCase serialization across all public and internal endpoints.

## Authentication Modes

WorkMesh supports two runtime authentication modes:
- **Production Mode (`AUTH_MODE=prod`, default)**: Strict signed JWT authentication via `Authorization: Bearer <token>`. User ID (`sub`), role (`role`), and team groups (`groups`) are extracted strictly from cryptographic claims. Unsigned simulation headers are rejected with `401 Unauthorized`.
- **Development Mode (`AUTH_MODE=dev`)**: Permits `X-User-Id`, `X-User-Role`, and `X-User-Groups` headers for local test scripts and interactive debugging.

## Core Endpoints

| Method | Path | Purpose | Authentication |
|---|---|---|---|
| GET | `/health` | Liveness check. Returns `{"status": "ok"}`. | None |
| GET | `/ready` | Readiness check. Verifies live PostgreSQL connection. | None |
| POST | `/api/v1/search` | Permission-aware hybrid search (lexical + dense vector RRF). | User JWT / dev header |
| POST | `/api/v1/ask` | Grounded question answering with verifiable citations. | User JWT / dev header |
| GET | `/api/v1/sync/status` | Read connector sync status and source sync state. | ADMIN role required |
| GET | `/api/v1/admin/sync/status` | Admin-alias for connector sync status. | ADMIN role required |
| POST | `/api/v1/admin/sync/reset` | Reset connector checkpoint cursor or acquire lease. | ADMIN role required |
| GET | `/api/v1/admin/audit/events` | Query recent audit logs with user/action filters. | ADMIN role required |
| GET | `/metrics` | Prometheus metrics and latency histograms. | None |

---

## POST /api/v1/search

Executes Reciprocal Rank Fusion (RRF) over full-text lexical search and dense embeddings (`all-MiniLM-L6-v2`), filtered by pushdown ACL permissions.

### Request Body

```json
{
  "query": "DC-8692 payment card verification",
  "limit": 10,
  "sourceTypes": ["GITHUB", "SLACK"]
}
```

### Response `200 OK`

```json
{
  "query": "DC-8692 payment card verification",
  "totalResults": 1,
  "results": [
    {
      "chunkId": "chunk:github:payment:1",
      "documentId": "doc:github:payments:pr:101",
      "sourceType": "GITHUB",
      "title": "Fix null verification in payment card validation (DC-8692)",
      "snippet": "Resolves ticket DC-8692: empty verification payloads were throwing NullPointerException...",
      "sourceUrl": "https://github.com/company/payments/pull/101",
      "author": "engineer_alice",
      "score": 0.0328
    }
  ],
  "searchTimeMs": 24,
  "status": "SUCCESS"
}
```

---

## POST /api/v1/ask

Synthesizes a grounded answer strictly from authorized evidence chunks, complete with bracketed citations `[1]`.

### Request Body

```json
{
  "question": "Why did we change the validation flow?",
  "sourceTypes": ["GITHUB", "SLACK"]
}
```

### Response `200 OK`

```json
{
  "question": "Why did we change the validation flow?",
  "answer": "According to the available evidence: empty verification payloads were throwing NullPointerException during checkout, so PaymentValidationService was updated to validate card tokens defensively and return HTTP 400 Bad Request [1].",
  "citations": [
    {
      "sourceType": "GITHUB",
      "title": "Fix null verification in payment card validation (DC-8692)",
      "url": "https://github.com/company/payments/pull/101",
      "snippet": "Resolves ticket DC-8692: empty verification payloads were throwing NullPointerException..."
    }
  ],
  "confidence": "HIGH",
  "status": "ANSWERED"
}
```

---

## Error Envelope Shape

All errors across public and admin endpoints return a uniform JSON error envelope with an active `request_id` matching the `X-Request-Id` response header:

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Authorization header missing or invalid",
    "request_id": "c8a41df2a1"
  }
}
```
