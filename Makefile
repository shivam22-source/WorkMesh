.PHONY: help preflight up down logs ps test test-rag run-api verify-db benchmark health metrics ingest-fixtures

help:
	@echo "preflight       Show local toolchain versions"
	@echo "up              Start PostgreSQL + pgvector"
	@echo "down            Stop PostgreSQL + pgvector"
	@echo "ps              Show container status"
	@echo "logs            Follow container logs"
	@echo "verify-db       Verify database readiness and pgvector extension via CLI"
	@echo "test            Run pytest test suite"
	@echo "benchmark       Run scale benchmark and real ablation evaluation"
	@echo "health          Check service readiness probe (/ready)"
	@echo "metrics         Fetch Prometheus metrics (/metrics)"
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

verify-db:
	cd rag-python && .venv/Scripts/python.exe -m app.cli.verify_db --require-pgvector

test: test-rag

test-rag:
	cd rag-python && .venv/Scripts/python.exe -m pytest

benchmark:
	cd rag-python && .venv/Scripts/python.exe scale_benchmark.py

health:
	curl -s http://127.0.0.1:8000/ready

metrics:
	curl -s http://127.0.0.1:8000/metrics

run-api:
	cd rag-python && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

ingest-fixtures:
	cd rag-python && .venv/Scripts/python.exe -m app.cli.ingest --source github --fixture --in-memory
