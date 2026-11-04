"""Locust load test suite for WorkMesh API concurrency and backpressure evaluation."""

import os
import random
import sys
import requests
from locust import HttpUser, between, task

# Ensure app package is importable from loadtest directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth.jwt_utils import create_jwt_token

TEST_QUERIES = [
    # 1. Exact Ticket IDs / Technical Identifiers (15)
    "DC-8692",
    "payment card validation",
    "HikariCP connection pool timeout",
    "JWT refresh token rotation",
    "Kafka consumer lag backpressure",
    "Redis cache stampede early expiration",
    "NullPointerException checkout",
    "dead letter queue malformed records",
    "leakDetectionThreshold starvation",
    "OAuth2 session expiry",
    "PR-1042",
    "CVE-2024-38819",
    "DC-1965",
    "DC-1980",
    "DC-7741",
    # 2. Architecture & Design Topics (15)
    "How does the permission pushdown architecture protect tenant data?",
    "Why was PostgreSQL full-text search chosen over dedicated Elasticsearch?",
    "How does token bucket rate limiting prevent service degradation?",
    "What is the disaster recovery and database backup procedure?",
    "How do we handle schema migrations across distributed environments?",
    "Explain the reciprocal rank fusion algorithm implementation",
    "What are the best practices for handling transient database disconnections?",
    "How does the audit logging system guarantee durability without blocking?",
    "Why did we migrate from 1536 zero-padded embeddings to 384 native dimensions?",
    "How are cross-source relationship graphs constructed between Slack and GitHub?",
    "Zero-trust authentication using asymmetric and symmetric signed JWTs",
    "Entity graph resolution for ticket employee document relationships",
    "Database fencing and distributed advisory locking for connector syncs",
    "Extractive grounded citations and hallucination mitigation strategy",
    "Deterministic reranking and lexical score normalization formulas",
    # 3. Operational & Engineering Topics (12)
    "fix payment verification flow",
    "docker compose healthcheck timeout postgres",
    "jwt token expiration and refresh handling",
    "ssl certificate renewal in kubernetes cluster",
    "memory leak in background sync worker",
    "postgres pgvector hnsw index parameters",
    "slack thread message normalization pipeline",
    "github webhook delivery failure retry strategy",
    "audit event retention and partitioning policy",
    "concurrency limit 503 retry-after header",
    "prometheus metrics scrape configuration",
    "fastapi lifespan startup validation checks",
    # 4. Multi-Source Connectors & Chunking (10)
    "GitHub pull request comment indexing and commit author resolution",
    "Slack channel access control lists and user group mapping",
    "Email connector MIME boundary parsing and header extraction",
    "Chunk token count boundary heuristics and markdown splitting",
    "pgvector cosine distance operator vs inner product",
    "Database connection pool exhaustion and keepalive settings",
    "Backpressure retry after header and graceful degradation",
    "Admin audit trail export and compliance filtering",
    "Connector sync state cursor checkpointing and replay",
    "Synthetic corpus scale benchmark and ablation evaluation",
]

TEST_QUESTIONS = [
    "Why did we change the validation flow?",
    "How was HikariCP connection pool tuned?",
    "What was the fix for Kafka consumer lag?",
    "How does JWT token rotation prevent logout?",
]

JWT_LOADTEST_SECRET = os.environ.get(
    "JWT_SECRET", "super_strong_production_loadtest_secret_key_at_least_32_characters_12345"
)
LOADTEST_USER_ID = os.environ.get("LOADTEST_USER_ID", "employee_42")


class WorkMeshUser(HttpUser):
    """Simulates realistic employee search and Q&A query behavior under load."""

    wait_time = between(0.05, 0.2)

    def on_start(self):
        groups = [] if LOADTEST_USER_ID == "test_user_1" else ["group_engineering", "group_backend"]
        self.token = create_jwt_token(
            user_id=LOADTEST_USER_ID,
            role="ENGINEER",
            groups=groups,
            secret=JWT_LOADTEST_SECRET,
            algorithm="HS256",
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        # Unmeasured warm-up query per virtual user (discarded from locust metrics)
        try:
            requests.post(
                f"{self.host}/api/v1/search",
                json={"query": "DC-8692", "limit": 5},
                headers=self.headers,
                timeout=15,
            )
        except Exception:
            pass

    @task(3)
    def search_query(self):
        query = random.choice(TEST_QUERIES)
        with self.client.post(
            "/api/v1/search",
            json={"query": query, "limit": 10},
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if 200 <= resp.status_code < 300:
                resp.request_meta["name"] = "Successful (2xx)"
                resp.success()
            elif resp.status_code == 503:
                resp.request_meta["name"] = "Backpressure (503 Shed)"
                resp.success()
            else:
                resp.request_meta["name"] = "Other Errors"
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:100]}")

    @task(1)
    def ask_question(self):
        question = random.choice(TEST_QUESTIONS)
        with self.client.post(
            "/api/v1/ask",
            json={"question": question},
            headers=self.headers,
            catch_response=True,
        ) as resp:
            if 200 <= resp.status_code < 300:
                resp.request_meta["name"] = "Successful (2xx)"
                resp.success()
            elif resp.status_code == 503:
                resp.request_meta["name"] = "Backpressure (503 Shed)"
                resp.success()
            else:
                resp.request_meta["name"] = "Other Errors"
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:100]}")
