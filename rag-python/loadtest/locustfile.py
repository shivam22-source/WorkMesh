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
]

TEST_QUESTIONS = [
    "Why did we change the validation flow?",
    "How was HikariCP connection pool tuned?",
    "What was the fix for Kafka consumer lag?",
    "How does JWT token rotation prevent logout?",
]

JWT_LOADTEST_SECRET = os.environ.get(
    "JWT_SECRET", "production_loadtest_strong_secret_key_at_least_32_characters_12345"
)


class WorkMeshUser(HttpUser):
    """Simulates realistic employee search and Q&A query behavior under load."""

    wait_time = between(0.05, 0.2)

    def on_start(self):
        self.token = create_jwt_token(
            user_id="employee_42",
            role="ENGINEER",
            groups=["group_engineering", "group_backend"],
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
