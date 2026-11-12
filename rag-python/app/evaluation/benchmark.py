"""Benchmark runner evaluating Recall@K, MRR, permission isolation, citations, and latency."""

import json
import logging
import time
from pathlib import Path
from typing import List, Optional

from app.connectors.email.fixture_adapter import EmailFixtureAdapter
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.contracts.rag_ask import RagAskRequest
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.evaluation.models import BenchmarkCase, BenchmarkCaseResult, BenchmarkSummary
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import KnowledgeRepository
from app.rag.service import GroundedRagService
from app.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Executes the standard WorkMesh evaluation benchmark suite."""

    def __init__(
        self,
        repository: KnowledgeRepository,
        retriever: Optional[HybridRetriever] = None,
        rag_service: Optional[GroundedRagService] = None,
    ):
        self.repository = repository
        self.retriever = retriever or HybridRetriever(repository=repository)
        self.rag_service = rag_service or GroundedRagService(retriever=self.retriever)

    def populate_fixtures(self) -> None:
        """Ingest all synthetic fixtures (GitHub, Slack, Email) into repository."""
        embedding_provider = MockEmbeddingProvider()
        connectors = [
            GitHubFixtureAdapter(),
            SlackFixtureAdapter(),
            EmailFixtureAdapter(),
        ]
        for conn in connectors:
            pipeline = IngestionPipeline(
                connector=conn,
                repository=self.repository,
                embedding_provider=embedding_provider,
            )
            pipeline.run()

    @staticmethod
    def default_dataset_path() -> Path:
        """Locate data/evaluation/benchmark_queries.json relative to repository root."""
        current = Path(__file__).resolve()
        # Traverse up until data/evaluation/benchmark_queries.json is found
        for parent in [current] + list(current.parents):
            candidate = parent / "data" / "evaluation" / "benchmark_queries.json"
            if candidate.exists():
                return candidate
        # Fallback to relative path
        return Path("data/evaluation/benchmark_queries.json")

    def load_dataset(self, filepath: Optional[str] = None) -> List[BenchmarkCase]:
        """Load benchmark evaluation queries from JSON dataset."""
        path = Path(filepath) if filepath else self.default_dataset_path()
        if not path.exists():
            raise FileNotFoundError(f"Evaluation dataset not found at {path}")

        with open(path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        cases: List[BenchmarkCase] = []
        for item in raw_data:
            cases.append(
                BenchmarkCase(
                    id=item["id"],
                    query=item["query"],
                    query_type=item.get("query_type", "keyword"),
                    description=item.get("description", ""),
                    expected_authoritative_sources=item.get("expected_authoritative_sources", []),
                    expected_keywords=item.get("expected_keywords", []),
                    authorized_user_id=item.get("authorized_user_id", "employee_42"),
                    authorized_group_ids=item.get("authorized_group_ids", []),
                    unauthorized_user_id=item.get("unauthorized_user_id"),
                    unauthorized_group_ids=item.get("unauthorized_group_ids", []),
                )
            )
        return cases

    def run_benchmark(
        self, cases: Optional[List[BenchmarkCase]] = None, dataset_path: Optional[str] = None
    ) -> BenchmarkSummary:
        """Run all evaluation queries and compute aggregate metrics."""
        if cases is None:
            cases = self.load_dataset(dataset_path)

        results: List[BenchmarkCaseResult] = []

        for case in cases:
            t0 = time.perf_counter()

            # 1. Authorized Retrieval
            auth_results = self.retriever.search(
                query=case.query,
                limit=10,
                user_id=case.authorized_user_id,
                group_ids=case.authorized_group_ids,
            )
            latency_ms = (time.perf_counter() - t0) * 1000.0

            retrieved_sources = [r.source_url for r in auth_results if r.source_url]

            # 2. Recall@K and Reciprocal Rank calculation
            first_rank = 0
            for idx, r in enumerate(auth_results):
                source_match = any(
                    expected in (r.source_url or "") or expected in (r.chunk_id or "")
                    for expected in case.expected_authoritative_sources
                )
                if source_match:
                    first_rank = idx + 1
                    break

            hit_at_1 = first_rank == 1
            hit_at_3 = 0 < first_rank <= 3
            hit_at_5 = 0 < first_rank <= 5
            reciprocal_rank = (1.0 / first_rank) if first_rank > 0 else 0.0

            # 3. Permission Isolation Check
            permission_leak = False
            if case.unauthorized_user_id:
                unauth_results = self.retriever.search(
                    query=case.query,
                    limit=10,
                    user_id=case.unauthorized_user_id,
                    group_ids=case.unauthorized_group_ids,
                )
                for ur in unauth_results:
                    if any(exp in (ur.source_url or "") for exp in case.expected_authoritative_sources):
                        permission_leak = True
                        break

            # 4. Grounded RAG synthesis and Citation correctness
            ask_req = RagAskRequest(
                question=case.query,
                user_id=case.authorized_user_id,
                group_ids=case.authorized_group_ids,
            )
            ask_resp = self.rag_service.ask(ask_req)

            citations_valid = True
            if ask_resp.status == "ANSWERED":
                if not ask_resp.citations:
                    citations_valid = False
                else:
                    for cit in ask_resp.citations:
                        if not cit.url or not cit.url.startswith("http"):
                            citations_valid = False
                            break

            results.append(
                BenchmarkCaseResult(
                    case_id=case.id,
                    query=case.query,
                    query_type=case.query_type,
                    hit_at_1=hit_at_1,
                    hit_at_3=hit_at_3,
                    hit_at_5=hit_at_5,
                    reciprocal_rank=reciprocal_rank,
                    retrieved_sources=retrieved_sources[:5],
                    citations_valid=citations_valid,
                    permission_leak=permission_leak,
                    latency_ms=latency_ms,
                    grounded=(ask_resp.status == "ANSWERED"),
                    details={
                        "confidence": ask_resp.confidence,
                        "status": ask_resp.status,
                        "citations_count": len(ask_resp.citations),
                    },
                )
            )

        total = len(results) or 1
        summary = BenchmarkSummary(
            total_queries=len(results),
            recall_at_1=sum(1 for r in results if r.hit_at_1) / total,
            recall_at_3=sum(1 for r in results if r.hit_at_3) / total,
            recall_at_5=sum(1 for r in results if r.hit_at_5) / total,
            mrr=sum(r.reciprocal_rank for r in results) / total,
            permission_leak_rate=sum(1 for r in results if r.permission_leak) / total,
            citation_validity_rate=sum(1 for r in results if r.citations_valid) / total,
            mean_latency_ms=sum(r.latency_ms for r in results) / total,
            case_results=results,
        )
        return summary
