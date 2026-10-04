.PHONY: help preflight up down logs ps test test-backend test-rag run-backend run-rag pg-ext-check

help:
	@echo "preflight       Show local toolchain versions"
	@echo "up              Start PostgreSQL + pgvector"
	@echo "down            Stop PostgreSQL + pgvector"
	@echo "ps              Show container status"
	@echo "logs            Follow container logs"
	@echo "pg-ext-check    Verify the vector extension exists"
	@echo "test            Run all tests"
	@echo "test-backend    Run backend-java tests"
	@echo "test-rag        Run rag-python tests"
	@echo "run-backend     Run backend-java on :8080"
	@echo "run-rag         Run rag-python on :8000"

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

test: test-backend test-rag

test-backend:
	cd backend-java && ./mvnw -B test

test-rag:
	cd rag-python && .venv/Scripts/python.exe -m pytest

run-backend:
	cd backend-java && ./mvnw spring-boot:run

run-rag:
	cd rag-python && .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000