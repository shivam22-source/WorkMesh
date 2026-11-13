"""GitHub fixture connector for deterministic local development and evaluation (AD-08).

Reads synthetic repository fixtures without making outbound HTTP calls.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from app.connectors.common.base import SourceConnector
from app.connectors.common.models import (
    AclReference,
    PrincipalType,
    RawSourceItem,
    SourceType,
)

logger = logging.getLogger(__name__)


class GitHubFixtureAdapter(SourceConnector):
    """Deterministic fixture adapter reading synthetic GitHub data from JSON."""

    def __init__(self, fixture_path: Optional[Path] = None):
        if fixture_path is None:
            # Default to data/fixtures/github/sample_github_data.json relative to project root
            base_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
            self.fixture_path = base_dir / "data" / "fixtures" / "github" / "sample_github_data.json"
        else:
            self.fixture_path = Path(fixture_path)

        self._items: List[RawSourceItem] = []
        self._loaded = False

    @property
    def source_type(self) -> SourceType:
        return SourceType.GITHUB

    def authenticate(self) -> bool:
        """Fixture adapter is always authenticated if the fixture file exists."""
        return self.fixture_path.exists()

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return

        if not self.fixture_path.exists():
            logger.warning("github_fixture_file_not_found path=%s", self.fixture_path)
            self._items = []
            self._loaded = True
            return

        with open(self.fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        repo = data.get("repository", "company/payment-service")
        items: List[RawSourceItem] = []

        # Parse Pull Requests
        for pr in data.get("pull_requests", []):
            pr_num = pr["number"]
            item_id = f"github:{repo}:pr:{pr_num}"
            created_at = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
            updated_at = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))

            raw_item = RawSourceItem(
                id=item_id,
                source_type=SourceType.GITHUB,
                source_id=str(pr_num),
                source_url=pr.get("html_url", f"https://github.com/{repo}/pull/{pr_num}"),
                title=pr.get("title", f"PR #{pr_num}"),
                author_id=pr.get("author", {}).get("login"),
                raw_content=pr.get("body", ""),
                metadata={
                    "repository": repo,
                    "kind": "pull_request",
                    "number": pr_num,
                    "state": pr.get("state", "open"),
                    "merged": pr.get("merged", False),
                    "author": pr.get("author", {}),
                    "head_branch": pr.get("head_branch"),
                    "base_branch": pr.get("base_branch"),
                    "changed_files": pr.get("changed_files", []),
                    "ticket_ids": pr.get("ticket_ids", []),
                    "comments": pr.get("comments", []),
                },
                created_at=created_at,
                updated_at=updated_at,
            )
            items.append(raw_item)

        # Parse Commits
        for commit in data.get("commits", []):
            sha = commit["sha"]
            item_id = f"github:{repo}:commit:{sha}"
            created_at = datetime.fromisoformat(commit["created_at"].replace("Z", "+00:00"))

            raw_item = RawSourceItem(
                id=item_id,
                source_type=SourceType.GITHUB,
                source_id=sha,
                source_url=commit.get("html_url", f"https://github.com/{repo}/commit/{sha}"),
                title=f"Commit {sha[:8]}: {commit.get('message', '').splitlines()[0]}",
                author_id=commit.get("author", {}).get("login"),
                raw_content=commit.get("message", ""),
                metadata={
                    "repository": repo,
                    "kind": "commit",
                    "sha": sha,
                    "author": commit.get("author", {}),
                    "changed_files": commit.get("changed_files", []),
                    "ticket_ids": commit.get("ticket_ids", []),
                },
                created_at=created_at,
                updated_at=created_at,
            )
            items.append(raw_item)

        # Sort chronologically by updated_at
        items.sort(key=lambda x: x.updated_at)
        self._items = items
        self._loaded = True
        logger.info("loaded_github_fixtures count=%d from=%s", len(items), self.fixture_path)

    def list_changes(
        self, cursor: Optional[str] = None
    ) -> Tuple[List[RawSourceItem], Optional[str]]:
        self._ensure_loaded()
        if not self._items:
            return [], cursor

        if cursor:
            try:
                cursor_dt = datetime.fromisoformat(cursor.replace("Z", "+00:00"))
                filtered = [item for item in self._items if item.updated_at > cursor_dt]
            except ValueError:
                filtered = self._items
        else:
            filtered = self._items

        if not filtered:
            return [], cursor

        next_cursor = filtered[-1].updated_at.isoformat()
        return filtered, next_cursor

    def fetch_item(self, item_id: str) -> Optional[RawSourceItem]:
        self._ensure_loaded()
        for item in self._items:
            if item.id == item_id or item.source_id == item_id:
                return item
        return None

    def build_source_link(self, item: RawSourceItem) -> str:
        return item.source_url

    def extract_acl(self, item: RawSourceItem) -> List[AclReference]:
        """Extract ACLs. Engineering repositories default to engineering team access."""
        return [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=item.id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_engineering",
                permission="READ",
            ),
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=item.id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_backend",
                permission="READ",
            ),
        ]
