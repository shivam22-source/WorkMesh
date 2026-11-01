"""CLI tool to fetch and demonstrate real live GitHub data integration."""

import argparse
import sys
from app.connectors.github.api_adapter import GitHubApiAdapter


def main():
    parser = argparse.ArgumentParser(description="Fetch real live data from any public or private GitHub repository.")
    parser.add_argument("--repo", default="pallets/flask", help="Target GitHub repository in 'owner/repo' format (default: pallets/flask)")
    parser.add_argument("--token", default=None, help="Optional GitHub Personal Access Token (for private repos or higher rate limits)")
    parser.add_argument("--limit", type=int, default=5, help="Number of preview items to display (default: 5)")
    args = parser.parse_args()

    print(f"\n=======================================================")
    print(f"       CONNECTING TO LIVE GITHUB REST API (v3)")
    print(f"=======================================================")
    print(f"Repository: {args.repo}")
    print(f"Authenticated: {'Yes (Token provided)' if args.token else 'No (Public anonymous access)'}")
    print(f"Fetching Pull Requests and Commits from api.github.com...")

    adapter = GitHubApiAdapter(repo=args.repo, token=args.token)
    items, next_cursor = adapter.list_changes()

    if not items:
        print(f"\n[ERROR] No items fetched. Please check repository name or token permissions.")
        sys.exit(1)

    print(f"\n[SUCCESS] Successfully fetched {len(items)} real items from GitHub API!")
    print(f"-------------------------------------------------------")
    print(f"Sample Normalized Items Preview:")
    for idx, item in enumerate(items[:args.limit], start=1):
        kind = item.metadata.get("kind", "item")
        print(f"{idx}. [{kind.upper()}] #{item.source_id}: {item.title}")
        print(f"   Author:  @{item.author_id}")
        print(f"   URL:     {item.source_url}")
        print(f"   Created: {item.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if item.created_at else 'N/A'}")
        print(f"   Preview: {item.raw_content[:80].strip()}...")
        print()
    print(f"=======================================================\n")


if __name__ == "__main__":
    main()
