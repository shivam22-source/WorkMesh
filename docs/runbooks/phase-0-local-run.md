# Phase 0 Runbook — Local Run

Verified on Windows 11, Temurin JDK 21.0.12, Maven 3.9.11, Python 3.13.0rc3,
Docker Desktop 29.6.2.

## Prerequisites

| Tool | Expected | Notes |
|---|---|---|
| JDK | 21+ | `java -version`. Phase 0 uses records, so 17 is the hard floor. |
| Maven | 3.9+ | Or use the bundled `./mvnw`. |
| Python | 3.12+ | `pyproject.toml` enforces `>=3.12`. |
| Docker Desktop | any recent | Only needed for PostgreSQL + pgvector. |

Check everything at once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/preflight-check.ps1
```

The script never fails. A missing tool is reported, not raised.

### After installing a JDK, open a new terminal

An already-open shell keeps its old environment. If `preflight-check.ps1` reports
Java 1.8 or a missing `javac`/`mvn` but you have just installed the JDK, close
and reopen the terminal before debugging anything else.

The preflight script reads `PATH` from the live process, so it can only report
what that process inherited.

## Step 1 — Configuration

```bash
cp .env.example .env
```

`.env` is git-ignored. `.env.example` holds only placeholders and is committed.
On PowerShell: `Copy-Item .env.example .env`.

The defaults work as-is for local development. Change `POSTGRES_PASSWORD` if you
care about the local instance.

## Step 2 — PostgreSQL + pgvector

```bash
make up          # docker compose up -d
make ps          # wait for STATUS to show (healthy)
make pg-ext-check
```

Expected from `make pg-ext-check`:

```text
 vector  | 0.8.7
```

If the extension is missing, the volume was initialised before the init script
existed. Reset it:

```bash
docker compose down -v
make up
```

## Step 3 — rag-python

```bash
cd rag-python
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Expected startup:

```text
INFO:     Uvicorn running on http://127.0.0.1:8000
{"ts":"...","level":"INFO","logger":"app.main","message":"..."}
```

Verify:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"rag-python"}

curl http://127.0.0.1:8000/ready
# {"status":"ok","service":"rag-python"}
```

## Step 4 — backend-java

```bash
cd backend-java
./mvnw spring-boot:run
```

On Windows use `mvnw.cmd spring-boot:run`.

Expected startup includes:

```text
rag_client_configured base_url=http://localhost:8000
```

Verify:

```bash
curl http://localhost:8080/actuator/health
# {"status":"UP"}
```

## Step 5 — Contract smoke test

With both services running:

```bash
curl -X POST http://127.0.0.1:8000/internal/v1/rag/health \
  -H "Content-Type: application/json" \
  -d '{"requestedBy":"backend-java","requestedAt":"2026-10-04T12:00:00Z"}'
```

Expected:

```json
{"status":"ok","service":"rag-python","contractVersion":"v1","message":"contract stub alive"}
```

The same path is exercised by `RestClientRagServiceClientTest` without needing a
running Python service, so the unit test remains the source of truth and this
step is the live confirmation.

## Step 6 — Tests

```bash
make test           # both suites
make test-backend   # backend-java, JUnit via Maven
make test-rag       # rag-python, pytest
```

Neither suite needs PostgreSQL, Docker, or the other service. This is
intentional: a contract test that needs both processes running is a contract
test that gets skipped.

## Troubleshooting

**`mvnw` fails on first run.** The wrapper downloads Maven on first use and needs
network access. It caches under `~/.m2/wrapper`.

**`java -version` reports 1.8.** Another JDK is first on `PATH`. Check
`echo %JAVA_HOME%` and confirm the JDK 21 `bin` precedes
`C:\Program Files\Java\jdk1.8.0_481\bin`.

**`could not find symbol: RagHealthResponse`.** A missing import in
`RagServiceClient` — the DTO lives in the `.dto` subpackage. Add
`import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;`.

**`422` from `/internal/v1/rag/health`.** The payload does not match the
contract. The wire format is camelCase; `requestedBy`, not `requested_by`. See
`docs/api/java-python-contract.md`.

A second cause is the h2c upgrade trap: if the Java client uses the default JDK
HttpClient instead of `SimpleClientHttpRequestFactory`, the POST body is silently
lost and Python reports `422 Field required`. Look for
`WARNING: Unsupported upgrade request` in the Python logs.

**`RagServiceUnavailableException` / `503`.** rag-python is not running, or
`RAG_BASE_URL` points somewhere else. The configured value is logged at startup
as `rag_client_configured base_url=...`.

**`docker compose` cannot find the daemon.** Start Docker Desktop and wait for
the whale to settle; the CLI can be on `PATH` before the engine is ready. Also
note Docker Desktop may be a per-user install under
`%LOCALAPPDATA%\Programs\DockerDesktop` rather than `C:\Program Files\Docker`.

**Path contains spaces, an em dash or `&`.** This repository intentionally lives
in an `employee-knowledge-rag` subfolder with a plain ASCII name. Maven, Compose
bind mounts and Make targets are unreliable when the parent path contains an
em dash. Keep the repository in that subfolder.

## Running without Docker

PostgreSQL 18 is installed locally on this machine. pgvector is not, so a native
fallback needs the extension installed:

```bash
psql -U <user> -d knowledge -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Until then, steps 3–6 all still work: no application code reads PostgreSQL in
Phase 0. Only `make up` and `make pg-ext-check` are blocked.

## Shutdown

```bash
make down           # stops the container, keeps the volume
docker compose down -v   # also deletes the volume
```