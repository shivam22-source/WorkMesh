.PHONY: help preflight up down logs ps test test-rag run-api pg-ext-check ingest-fixtures

help:
	@echo "preflight       Show local toolchain versions"
	@echo "up              Start PostgreSQL + pgvector"
	@echo "down            Stop PostgreSQL + pgvector"
	@echo "ps              Show container status"
	@echo "logs            Follow container logs"
	@echo "pg-ext-check    Verify the vector extension exists"
	@echo "test            Run pytest suite"
	@echo "run-api         Run WorkMesh API on :8000"
	@echo "ingest-fixtures Ingest synthetic fixtures into knowledge index"

preflight:
	@powershell -ExecutionPolicy Bypass -File scripts/preflight-check.ps1

up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f

pg-ext-check:
	docker exec ekr-postgres psql -U knowledge -d knowledge -t -c "SELECT extname, extversion FROM pg_extension WHERE extname='vector';"

test: test-rag

test-rag:
	cd rag-python && .venv/Scripts/python.exe -m pytest

run-api:
	cd rag-python && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

ingest-fixtures:
	cd rag-python && .venv/Scripts/python.exe -m app.cli.ingest --source github --fixture --in-memory
