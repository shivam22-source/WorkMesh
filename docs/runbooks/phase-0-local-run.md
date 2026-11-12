# WorkMesh Local Runbook

Instructions for setting up and running WorkMesh locally.

## Prerequisites

| Tool | Expected | Notes |
|---|---|---|
| Python | 3.12+ | `pyproject.toml` enforces `>=3.12`. |
| Docker Desktop | any recent | Runs PostgreSQL 16 + pgvector container. |

## Step 1 — Configuration

```bash
cp .env.example .env
```

On Windows PowerShell: `Copy-Item .env.example .env`.

The defaults point to PostgreSQL with credentials `knowledge:local_dev_only_change_me` on port 5432.

## Step 2 — PostgreSQL + pgvector

```bash
docker compose up -d postgres
```

Verify pgvector extension:

```bash
docker exec -it ekr-postgres psql -U knowledge -d knowledge -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

Expected output confirms `vector` is installed.

## Step 3 — WorkMesh API Service

```bash
cd rag-python
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Verify endpoints:

```bash
# Liveness
curl http://127.0.0.1:8000/health

# Readiness (checks live PostgreSQL connectivity)
curl http://127.0.0.1:8000/ready
```

## Step 4 — Run Ingestion

Ingest test fixtures across GitHub, Slack, and Email:

```bash
.venv/Scripts/python.exe -m app.cli.ingest --source all
```

## Step 5 — Run Evaluation Benchmark & Ablation

```bash
.venv/Scripts/python.exe -m app.cli.scale_benchmark --skip-seed --ablation
```

## Step 6 — Run Tests

```bash
cd rag-python
.venv/Scripts/pytest.exe tests
```

Tests run offline using mock embeddings by default, with optional real model verification when weights are cached.

## Troubleshooting

- **Database Connection Refused**: Verify the Docker container `ekr-postgres` is running via `docker ps`.
- **401 Unauthorized**: In production mode (`AUTH_MODE=prod`), requests require `Authorization: Bearer <token>`. Set `AUTH_MODE=dev` in your environment to test with header-based identity simulation.
- **Port Conflicts**: Ensure host port 5432 is not occupied by a local PostgreSQL installation.
