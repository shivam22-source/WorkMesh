"""Normalizer converting raw GitHub items into canonical documents."""

import re
from typing import List, Set

from app.connectors.common.models import AclReference, RawSourceItem
from app.normalization.common import extract_ticket_ids
from app.normalization.models import CanonicalDocument


class GitHubNormalizer:
    """Converts raw GitHub pull requests and commits into CanonicalDocuments."""

    def normalize(
        self, raw_item: RawSourceItem, acl_references: List[AclReference]
    ) -> CanonicalDocument:
        kind = raw_item.metadata.get("kind", "pull_request")
        if kind == "commit":
            return self._normalize_commit(raw_item, acl_references)
        return self._normalize_pull_request(raw_item, acl_references)

    def _extract_tickets(self, text: str) -> List[str]:
        return extract_ticket_ids(text)

    def _normalize_pull_request(
        self, item: RawSourceItem, acls: List[AclReference]
    ) -> CanonicalDocument:
        meta = item.metadata
        repo = meta.get("repository", "unknown-repo")
        pr_number = meta.get("number", item.source_id)
        author_name = item.author_id or "unknown"

        # Combine text for ticket extraction
        combined_text = f"{item.title or ''} {item.raw_content}"
        tickets = sorted(list(set(meta.get("ticket_ids", []) + self._extract_tickets(combined_text))))

        changed_files = meta.get("changed_files", [])
        comments = meta.get("comments", [])

        # Build clean structured markdown content
        sections = [
            f"# Pull Request #{pr_number}: {item.title}",
            f"**Repository:** `{repo}` | **Status:** `{meta.get('state', 'open')}` (Merged: {meta.get('merged', False)})",
            f"**Author:** {author_name} | **Branch:** `{meta.get('head_branch', '')}` → `{meta.get('base_branch', 'main')}`",
        ]

        if tickets:
            sections.append(f"**Referenced Tickets:** {', '.join(tickets)}")

        sections.append("## Description\n" + (item.raw_content.strip() or "No description provided."))

        if changed_files:
            file_lines = "\n".join(f"- `{f}`" for f in changed_files)
            sections.append(f"## Changed Files ({len(changed_files)})\n{file_lines}")

        if comments:
            comment_blocks = []
            for c in comments:
                c_author = c.get("author", "reviewer")
                c_body = c.get("body", "")
                comment_blocks.append(f"**{c_author}:** {c_body}")
            sections.append("## Discussion & Reviews\n" + "\n\n".join(comment_blocks))

        canonical_content = "\n\n".join(sections)
        doc_id = f"doc:{item.id}"
        formatted_title = f"Pull Request #{pr_number}: {item.title}" if item.title else f"Pull Request #{pr_number}"

        doc_meta = {
            "repository": repo,
            "kind": "pull_request",
            "number": pr_number,
            "state": meta.get("state"),
            "merged": meta.get("merged", False),
            "ticket_ids": tickets,
            "changed_files": changed_files,
            "author": author_name,
        }

        return CanonicalDocument(
            id=doc_id,
            source_record_id=item.id,
            source_type=item.source_type.value,
            title=formatted_title,
            content=canonical_content,
            author=author_name,
            url=item.source_url,
            metadata=doc_meta,
            acl_references=acls,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    def _normalize_commit(
        self, item: RawSourceItem, acls: List[AclReference]
    ) -> CanonicalDocument:
        meta = item.metadata
        repo = meta.get("repository", "unknown-repo")
        sha = meta.get("sha", item.source_id)
        short_sha = sha[:8]
        author_name = item.author_id or "unknown"

        combined_text = f"{item.title or ''} {item.raw_content}"
        tickets = sorted(list(set(meta.get("ticket_ids", []) + self._extract_tickets(combined_text))))
        changed_files = meta.get("changed_files", [])

        sections = [
            f"# Commit {short_sha}: {item.title}",
            f"**Repository:** `{repo}` | **SHA:** `{sha}`",
            f"**Author:** {author_name}",
        ]

        if tickets:
            sections.append(f"**Referenced Tickets:** {', '.join(tickets)}")

        sections.append("## Commit Message\n" + item.raw_content.strip())

        if changed_files:
            file_lines = "\n".join(f"- `{f}`" for f in changed_files)
            sections.append(f"## Touched Files ({len(changed_files)})\n{file_lines}")

        canonical_content = "\n\n".join(sections)
        doc_id = f"doc:{item.id}"
        formatted_title = f"Commit {short_sha}: {item.title}" if item.title else f"Commit {short_sha}"

        doc_meta = {
            "repository": repo,
            "kind": "commit",
            "sha": sha,
            "short_sha": short_sha,
            "ticket_ids": tickets,
            "changed_files": changed_files,
            "author": author_name,
        }

        return CanonicalDocument(
            id=doc_id,
            source_record_id=item.id,
            source_type=item.source_type.value,
            title=formatted_title,
            content=canonical_content,
            author=author_name,
            url=item.source_url,
            metadata=doc_meta,
            acl_references=acls,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
