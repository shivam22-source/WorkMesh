"""Real GitHub API connector using GitHub REST API v3 (AD-08).

Fetches Pull Requests and Commits over HTTPS if credentials are provided.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from app.connectors.common.base import SourceConnector
from app.connectors.common.models import (
    AclReference,
    PrincipalType,
    RawSourceItem,
    SourceType,
)

logger = logging.getLogger(__name__)


class GitHubApiAdapter(SourceConnector):
    """Production GitHub API connector using token-based authentication."""

    def __init__(
        self,
        repo: str,
        token: Optional[str] = None,
        base_url: str = "https://api.github.com",
    ):
        self.repo = repo
        self.token = token
        self.base_url = base_url.rstrip("/")

    @property
    def source_type(self) -> SourceType:
        return SourceType.GITHUB

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "WorkMesh-Employee-Knowledge-RAG/0.0.1",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    def authenticate(self) -> bool:
        if not self.repo:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(
                    f"{self.base_url}/repos/{self.repo}",
                    headers=self._headers(),
                )
                return res.status_code == 200
        except Exception as e:
            logger.warning("github_auth_check_failed repo=%s err=%s", self.repo, e)
            return False

    def list_changes(
        self, cursor: Optional[str] = None
    ) -> Tuple[List[RawSourceItem], Optional[str]]:
        if not self.authenticate():
            logger.warning("github_api_not_authenticated repo=%s", self.repo)
            return [], cursor

        items: List[RawSourceItem] = []
        params = {"state": "all", "sort": "updated", "direction": "asc", "per_page": 50}
        if cursor:
            params["since"] = cursor

        try:
            with httpx.Client(timeout=15.0) as client:
                # 1. Fetch Pull Requests
                pr_res = client.get(
                    f"{self.base_url}/repos/{self.repo}/pulls",
                    headers=self._headers(),
                    params=params,
                )
                if pr_res.status_code == 200:
                    for pr in pr_res.json():
                        pr_num = pr["number"]
                        created_at = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
                        updated_at = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
                        items.append(
                            RawSourceItem(
                                id=f"github:{self.repo}:pr:{pr_num}",
                                source_type=SourceType.GITHUB,
                                source_id=str(pr_num),
                                source_url=pr.get("html_url", f"https://github.com/{self.repo}/pull/{pr_num}"),
                                title=pr.get("title", f"PR #{pr_num}"),
                                author_id=pr.get("user", {}).get("login"),
                                raw_content=pr.get("body") or "",
                                metadata={
                                    "repository": self.repo,
                                    "kind": "pull_request",
                                    "number": pr_num,
                                    "state": pr.get("state"),
                                    "merged": pr.get("merged", False),
                                    "author": pr.get("user", {}),
                                },
                                created_at=created_at,
                                updated_at=updated_at,
                            )
                        )

                # 2. Fetch Commits
                commit_params = {"per_page": 50}
                if cursor:
                    commit_params["since"] = cursor
                commit_res = client.get(
                    f"{self.base_url}/repos/{self.repo}/commits",
                    headers=self._headers(),
                    params=commit_params,
                )
                if commit_res.status_code == 200:
                    for c in commit_res.json():
                        sha = c["sha"]
                        c_data = c.get("commit", {})
                        author_info = c_data.get("author", {})
                        dt_str = author_info.get("date", datetime.now(timezone.utc).isoformat())
                        created_at = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                        msg = c_data.get("message", "")
                        items.append(
                            RawSourceItem(
                                id=f"github:{self.repo}:commit:{sha}",
                                source_type=SourceType.GITHUB,
                                source_id=sha,
                                source_url=c.get("html_url", f"https://github.com/{self.repo}/commit/{sha}"),
                                title=f"Commit {sha[:8]}: {msg.splitlines()[0] if msg else 'Update'}",
                                author_id=author_info.get("name"),
                                raw_content=msg,
                                metadata={
                                    "repository": self.repo,
                                    "kind": "commit",
                                    "sha": sha,
                                    "author": author_info,
                                },
                                created_at=created_at,
                                updated_at=created_at,
                            )
                        )
        except Exception as e:
            logger.error("github_api_fetch_failed repo=%s err=%s", self.repo, e)
            raise

        items.sort(key=lambda x: x.updated_at)
        next_cursor = items[-1].updated_at.isoformat() if items else cursor
        return items, next_cursor

    def fetch_item(self, item_id: str) -> Optional[RawSourceItem]:
        # For simplicity, delegate to list_changes or single fetch
        return None

    def build_source_link(self, item: RawSourceItem) -> str:
        return item.source_url

    def extract_acl(self, item: RawSourceItem) -> List[AclReference]:
        return [
            AclReference(
                resource_type="SOURCE_RECORD",
                resource_id=item.id,
                principal_type=PrincipalType.GROUP,
                principal_id="group_engineering",
                permission="READ",
            )
        ]
