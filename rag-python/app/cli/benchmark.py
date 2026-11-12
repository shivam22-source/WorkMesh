"""CLI command to run the WorkMesh evaluation benchmark suite."""

import argparse
import json
import logging

from app.common.config import get_settings
from app.evaluation.benchmark import BenchmarkRunner
from app.indexing.repository import InMemoryKnowledgeRepository, PostgresKnowledgeRepository

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger("cli.benchmark")


def main():
    parser = argparse.ArgumentParser(description="WorkMesh Retrieval & Grounded RAG Evaluation Benchmark")
    parser.add_argument(
        "--in-memory",
        dest="in_memory",
        action="store_true",
        default=True,
        help="Run against populated in-memory repository (default: True)",
    )
    parser.add_argument(
        "--postgres",
        dest="in_memory",
        action="store_false",
        help="Run against PostgreSQL database",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Path to custom evaluation dataset JSON",
    )
    parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        default=False,
        help="Output raw JSON summary instead of formatted report",
    )

    args = parser.parse_args()

    if args.in_memory:
        logger.info("Initializing in-memory repository with synthetic fixtures...")
        repo = InMemoryKnowledgeRepository()
        runner = BenchmarkRunner(repository=repo)
        runner.populate_fixtures()
    else:
        settings = get_settings()
        logger.info("Connecting to PostgreSQL at %s", settings.database_url)
        repo = PostgresKnowledgeRepository(connection_url=settings.database_url)
        runner = BenchmarkRunner(repository=repo)

    logger.info("Running evaluation benchmark...")
    summary = runner.run_benchmark(dataset_path=args.dataset)

    if args.output_json:
        print(json.dumps(summary.to_dict(), indent=2))
        return

    print("\n" + "=" * 65)
    print("           WORKMESH EVALUATION BENCHMARK REPORT")
    print("=" * 65)
    print(f"Total Evaluated Queries:       {summary.total_queries}")
    print(f"Recall@1:                      {summary.recall_at_1 * 100:.1f}%")
    print(f"Recall@3:                      {summary.recall_at_3 * 100:.1f}%")
    print(f"Recall@5:                      {summary.recall_at_5 * 100:.1f}%")
    print(f"Mean Reciprocal Rank (MRR):    {summary.mrr:.4f}")
    print(f"Permission Leak Rate:          {summary.permission_leak_rate * 100:.1f}%  (target: 0.0%)")
    print(f"Citation Validity Rate:        {summary.citation_validity_rate * 100:.1f}%  (target: 100.0%)")
    print(f"Mean Retrieval Latency:        {summary.mean_latency_ms:.2f} ms")
    print("-" * 65)
    print(f"{'Case ID':<10} {'Type':<18} {'R@1':<5} {'R@5':<5} {'MRR':<8} {'Leak':<6} {'Query'}")
    print("-" * 65)
    for cr in summary.case_results:
        leak_str = "LEAK!" if cr.permission_leak else "OK"
        print(
            f"{cr.case_id:<10} {cr.query_type:<18} {str(cr.hit_at_1):<5} {str(cr.hit_at_5):<5} "
            f"{cr.reciprocal_rank:<8.2f} {leak_str:<6} {cr.query[:30]}"
        )
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
