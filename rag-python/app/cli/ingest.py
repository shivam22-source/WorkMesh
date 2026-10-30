"""Local CLI script to run knowledge ingestion (e.g. from GitHub fixtures or API)."""

import argparse
import logging
import sys

from app.common.config import get_settings
from app.connectors.github.api_adapter import GitHubApiAdapter
from app.connectors.github.fixture_adapter import GitHubFixtureAdapter
from app.connectors.slack.fixture_adapter import SlackFixtureAdapter
from app.embeddings.factory import get_embedding_provider
from app.indexing.pipeline import IngestionPipeline
from app.indexing.repository import (
    InMemoryKnowledgeRepository,
    PostgresKnowledgeRepository,
)

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger("cli.ingest")


def main():
    parser = argparse.ArgumentParser(description="WorkMesh Knowledge Ingestion CLI")
    parser.add_argument(
        "--source",
        choices=["github", "slack"],
        default="github",
        help="Source system to ingest (default: github)",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        default=True,
        help="Use deterministic synthetic fixtures (default: True)",
    )
    parser.add_argument(
        "--live",
        dest="fixture",
        action="store_false",
        help="Connect to live API instead of fixtures",
    )
    parser.add_argument(
        "--in-memory",
        dest="in_memory",
        action="store_true",
        default=False,
        help="Use in-memory repository instead of PostgreSQL",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repository slug (for live GitHub API, e.g. company/repo)",
    )

    args = parser.parse_args()
    settings = get_settings()

    # 1. Resolve connector
    if args.fixture:
        logger.info("using_fixture_connector source=%s", args.source)
        if args.source == "slack":
            connector = SlackFixtureAdapter()
        else:
            connector = GitHubFixtureAdapter()
    else:
        if args.source == "slack":
            logger.error("live_slack_api_not_supported_in_step_1 use --fixture for slack ingestion")
            sys.exit(1)
        repo = args.repo or settings.github_repo
        if not repo:
            logger.error("missing_repo_for_live_ingestion specify --repo or GITHUB_REPO")
            sys.exit(1)
        logger.info("using_live_api_connector repo=%s", repo)
        connector = GitHubApiAdapter(repo=repo, token=settings.github_token)

    # 2. Resolve repository
    if args.in_memory:
        logger.info("using_in_memory_repository")
        repo_impl = InMemoryKnowledgeRepository()
    else:
        try:
            logger.info("connecting_to_postgres url=%s", settings.database_url.replace(settings.postgres_password, "*****"))
            repo_impl = PostgresKnowledgeRepository(settings.database_url)
            # Quick check if database is reachable
            repo_impl.get_sync_state("GITHUB")
            logger.info("connected_to_postgres_successfully")
        except Exception as e:
            logger.warning("postgres_unreachable_falling_back_to_in_memory: %s", e)
            repo_impl = InMemoryKnowledgeRepository()

    # 3. Resolve embedding provider
    embedding_provider = get_embedding_provider()

    # 4. Build and run pipeline
    pipeline = IngestionPipeline(
        connector=connector,
        repository=repo_impl,
        embedding_provider=embedding_provider,
    )

    result = pipeline.run()

    print("\n" + "=" * 60)
    print("INGESTION RUN SUMMARY")
    print("=" * 60)
    print(f"Source:           {result.source_type}")
    print(f"Status:           {result.status}")
    print(f"Records Ingested: {result.records_ingested}")
    print(f"Chunks Indexed:   {result.chunks_indexed}")
    print(f"New Checkpoint:   {result.new_cursor}")
    if result.error_message:
        print(f"Error Message:    {result.error_message}")
    print("=" * 60 + "\n")

    if result.status != "SUCCESS":
        sys.exit(1)


if __name__ == "__main__":
    main()
