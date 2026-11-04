"""Locust load test suite for WorkMesh API concurrency and backpressure evaluation."""

import os
import random
import sys
from locust import HttpUser, between, task

# Ensure app package is importable from loadtest directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth.jwt_utils import create_jwt_token
from app.common.config import get_settings

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


class WorkMeshUser(HttpUser):
    """Simulates realistic employee search and Q&A query behavior under load."""

    wait_time = between(0.05, 0.2)

    def on_start(self):
        settings = get_settings()
        self.token = create_jwt_token(
            user_id="employee_42",
            role="ENGINEER",
            groups=["group_engineering", "group_backend"],
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @task(3)
    def search_query(self):
        query = random.choice(TEST_QUERIES)
        self.client.post(
            "/api/v1/search",
            json={"query": query, "limit": 10},
            headers=self.headers,
            name="/api/v1/search",
        )

    @task(1)
    def ask_question(self):
        question = random.choice(TEST_QUESTIONS)
        self.client.post(
            "/api/v1/ask",
            json={"question": question},
            headers=self.headers,
            name="/api/v1/ask",
        )
