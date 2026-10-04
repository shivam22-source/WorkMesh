# Java → Python Service Contract (v1)

Phase 0 defines a single contract endpoint. Its purpose is to prove that both
services agree on a wire format before any real payload is exchanged.

- Java caller: `com.company.knowledge.orchestrator.ragclient.RagServiceClient`
- Java DTOs: `com.company.knowledge.orchestrator.ragclient.dto`
- Python implementation: `app/api/internal_rag.py`
- Python schema: `app/contracts/rag_health.py`

## Naming rule

The wire format is **camelCase**.

Java records serialise to camelCase by default; Pydantic defaults to snake_case.
Every multi-word field in `app/contracts/rag_health.py` therefore carries an
explicit `validation_alias` / `serialization_alias`. This is not stylistic — the
Phase 0 contract test failed with HTTP 422 before the aliases were added,
because Java sent `requestedBy` and Pydantic expected `requested_by`.

## Versioning

All internal endpoints live under `/internal/v1/`. A breaking change to any
payload means a new version prefix (`/internal/v2/`) with both versions served
until every caller has moved. Adding an optional field is not a breaking change.

`contractVersion` in the response body is the contract's own version string, not
the path prefix. They are expected to move together.

## Endpoints

| Method | Path | Purpose | Auth (Phase 0) |
|---|---|---|---|
| GET | `/health` | Liveness. Process is up. | none |
| GET | `/ready` | Readiness. Process can do real work. | none |
| POST | `/internal/v1/rag/health` | Contract round-trip check. | none |

`/health` must never depend on Postgres or any other service — a liveness probe
that fails on a database blip causes a restart loop.

`/ready` **currently checks nothing.** Phase 0 has no database client. Phase 1
must make `/ready` verify Postgres connectivity before any feature depends on it.

## POST /internal/v1/rag/health

Request:

```json
{
  "requestedBy": "backend-java",
  "requestedAt": "2026-10-04T12:00:00Z"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `requestedBy` | string | yes | Caller name. Only `backend-java` today. |
| `requestedAt` | string (ISO-8601) | yes | Caller clock. Informational only. |

Response `200`:

```json
{
  "status": "ok",
  "service": "rag-python",
  "contractVersion": "v1",
  "message": "contract stub alive"
}
```

| Field | Type | Notes |
|---|---|---|
| `status` | string | Literal `ok`. Anything else is a failure. |
| `service` | string | Literal `rag-python`. |
| `contractVersion` | string | Currently `v1`. |
| `message` | string | Human-readable, for logs and demos only. |

Java maps this to the `RagHealthResponse` record.

## Error shape

Both services return the same error body so a client sees one contract:

```json
{
  "timestamp": "2026-10-04T12:00:00Z",
  "status": 500,
  "error": "Internal Server Error",
  "message": "unexpected server error",
  "path": "/internal/v1/rag/health",
  "traceId": null
}
```

Java includes `timestamp` and `traceId`; the Python handler currently omits
`timestamp` because FastAPI's built-in error path does not add it. This is a
known, small inconsistency — align it when the first real endpoint lands rather
than adding a custom exception handler now for one stub endpoint.

`message` is always generic on a 500. The detail goes to the log so internals
cannot leak to a caller.

## Validation

`422 Unprocessable Entity` is returned when:

- a required field is missing
- a field has the wrong type
- an unknown field is present (`extra="forbid"`)

Rejecting unknown fields is deliberate. It turns a silent typo — a field that
looks right but is never read — into a loud failure.

## Failure handling

| Situation | Python response | Java behaviour |
|---|---|---|
| Service down / DNS fail | connection refused | `RagServiceUnavailableException` → `503` |
| Timeout | no response | `RagServiceUnavailableException` → `503` |
| Python 5xx | 500 with `ApiError` shape | `RagServiceUnavailableException` → `503` |
| Bad request body | 422 | `RagServiceUnavailableException` → `503` |
| Empty 200 body | 200, no body | `RagServiceUnavailableException` → `503` |

An empty body is treated as unavailable rather than as success, because a 200
with no payload means the contract is already broken.

Note that Java currently maps every failure mode to `503`, including a `422`
caused by Java's own malformed request. Phase 1 should distinguish
"my request was wrong" (→ `500`, a bug in backend-java) from "the RAG service is
down" (→ `503`). Flagged rather than pre-built.

Timeouts are explicit: 2s connect, 10s read, both overridable via
`RAG_CONNECT_TIMEOUT` and `RAG_READ_TIMEOUT`.

### HTTP version trap

The Java client must use an HTTP/1.1-only request factory. A bare
`RestClient.builder()` selects the JDK HttpClient, which attempts an HTTP/2
cleartext (h2c) upgrade. Uvicorn rejects that upgrade and **the request body is
lost** — rag-python replies `422 "Field required"` for a body Java is certain it
sent, which looks like a contract bug rather than a transport bug.

`RagClientConfig` pins `SimpleClientHttpRequestFactory` to prevent this. Observed
live in Phase 0: `WARNING: Unsupported upgrade request` on the Python side
alongside the 422.

The mock-based unit test does **not** catch this, because `MockRestServiceServer`
never opens a socket. Any future change to the transport must be re-verified
against a running rag-python, not just against the unit test.

## Security status

**This contract is unauthenticated.** That is acceptable in Phase 0 only because
no real or sensitive data crosses it — the payload is a static health string.

Before any real data flows, backend-java → rag-python must be authenticated with
a shared secret or mTLS, sourced from the environment or a secret manager. This
is a hard prerequisite for Phase 2, not an optional hardening item.

## Drift protection

Both sides carry a test that asserts the exact wire shape:

- `backend-java/.../RestClientRagServiceClientTest` — asserts the URL, method,
  request body field and each response field.
- `rag-python/tests/test_rag_contract.py` — asserts the response key set matches
  `{"status", "service", "contractVersion", "message"}` exactly.

If either side is changed without the other, a test fails rather than a request
failing at runtime. This is the mechanism that caught the camelCase bug in
Phase 0.