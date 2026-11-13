"""Deterministic extraction of knowledge graph entities and relationships (AD-03).

Extracts canonical entities:
- TICKET (source_record_id is ALWAYS None)
- PULL_REQUEST (anchored to source_records.id)
- COMMIT (anchored to source_records.id)
- SLACK_THREAD (anchored to source_records.id)
- EMPLOYEE (source_record_id is ALWAYS None)

Extracts canonical directed relationships:
- TICKET --discussed_in--> SLACK_THREAD
- TICKET --implemented_by--> PULL_REQUEST
- PULL_REQUEST --contains--> COMMIT
- COMMIT --authored_by--> EMPLOYEE
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from app.connectors.common.models import RawSourceItem, SourceType
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.normalization.common import extract_ticket_ids
from app.normalization.models import CanonicalDocument

logger = logging.getLogger(__name__)

PR_PATTERN = re.compile(r"(?:PR\s*#?|pull/?)(\d+)", re.IGNORECASE)


def extract_entities_and_relationships(
    raw_items: List[RawSourceItem],
    docs: Optional[List[CanonicalDocument]] = None,
) -> Tuple[List[Entity], List[Relationship]]:
    """Extract canonical entities and relationships deterministically from ingested items.

    Enforces invariants:
    - TICKET and EMPLOYEE always have source_record_id = None.
    - PULL_REQUEST, COMMIT, and SLACK_THREAD always have a non-null source_record_id.
    - Canonical directed relationships only (no automatic inverse edges).
    """
    entities: Dict[str, Entity] = {}
    relationships: Dict[Tuple[str, str, str], Relationship] = {}

    def add_entity(entity: Entity) -> None:
        # Invariant: TICKET and EMPLOYEE must always have source_record_id = None
        if entity.entity_type in {EntityType.TICKET.value, EntityType.EMPLOYEE.value}:
            entity.source_record_id = None

        if entity.id in entities:
            existing = entities[entity.id]
            # Merge metadata
            merged_meta = {**existing.metadata, **entity.metadata}
            existing.metadata = merged_meta
            if existing.source_record_id is None and entity.source_record_id is not None:
                if entity.entity_type not in {EntityType.TICKET.value, EntityType.EMPLOYEE.value}:
                    existing.source_record_id = entity.source_record_id
        else:
            entities[entity.id] = entity

    def add_relationship(
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        metadata: Optional[Dict] = None,
        source_record_id: Optional[str] = None,
    ) -> None:
        key = (source_id, target_id, rel_type.value)
        meta = dict(metadata or {})
        if source_record_id:
            meta["source_record_id"] = source_record_id
            meta["source_record_ids"] = [source_record_id]
        if key not in relationships:
            relationships[key] = Relationship(
                source_entity_id=source_id,
                target_entity_id=target_id,
                relationship_type=rel_type.value,
                metadata=meta,
            )
        else:
            existing = relationships[key]
            if source_record_id:
                sids = set(existing.metadata.get("source_record_ids", []))
                if existing.metadata.get("source_record_id"):
                    sids.add(existing.metadata["source_record_id"])
                sids.add(source_record_id)
                existing.metadata["source_record_ids"] = sorted(list(sids))

    # Track PRs and Commits by ticket and repo for deterministic linking
    prs_by_ticket: Dict[Tuple[str, str], List[str]] = {}  # (repo, ticket) -> [pr_entity_id]
    commits_by_ticket: Dict[Tuple[str, str], List[str]] = {}  # (repo, ticket) -> [commit_entity_id]
    prs_by_num: Dict[Tuple[str, str], str] = {}  # (repo, pr_num) -> pr_entity_id

    for item in raw_items:
        meta = item.metadata or {}

        # -------------------------------------------------------------------
        # 1. GitHub Pull Requests and Commits
        # -------------------------------------------------------------------
        if item.source_type == SourceType.GITHUB:
            repo = meta.get("repository", "unknown-repo")
            kind = meta.get("kind", "").lower()

            # Handle Pull Request
            if kind == "pull_request" or "pull" in item.source_url:
                pr_num = str(meta.get("number", item.source_id))
                pr_id = f"pr:{repo}:{pr_num}"
                pr_name = item.title or f"Pull Request #{pr_num}"
                prs_by_num[(repo, pr_num)] = pr_id

                add_entity(
                    Entity(
                        id=pr_id,
                        entity_type=EntityType.PULL_REQUEST.value,
                        name=pr_name,
                        source_record_id=item.id,
                        metadata={
                            "repository": repo,
                            "number": pr_num,
                            "url": item.source_url,
                            "state": meta.get("state", "open"),
                            "merged": meta.get("merged", False),
                        },
                        created_at=item.created_at,
                    )
                )

                # Extract referenced tickets
                combined_text = f"{item.title or ''} {item.raw_content}"
                tickets = sorted(list(set(meta.get("ticket_ids", []) + extract_ticket_ids(combined_text))))
                for tid in tickets:
                    ticket_id = f"ticket:{tid}"
                    add_entity(
                        Entity(
                            id=ticket_id,
                            entity_type=EntityType.TICKET.value,
                            name=tid,
                            source_record_id=None,
                            metadata={"ticket_id": tid},
                            created_at=item.created_at,
                        )
                    )
                    # Canonical: TICKET --implemented_by--> PULL_REQUEST
                    add_relationship(
                        source_id=ticket_id,
                        target_id=pr_id,
                        rel_type=RelationshipType.IMPLEMENTED_BY,
                        metadata={"repository": repo, "pr_number": pr_num},
                        source_record_id=item.id,
                    )
                    prs_by_ticket.setdefault((repo, tid), []).append(pr_id)

                # Explicit commits list in PR metadata if present
                for c in meta.get("commits", []):
                    c_sha = c.get("sha") if isinstance(c, dict) else str(c)
                    commit_entity_id = f"commit:{repo}:{c_sha}"
                    # Canonical: PULL_REQUEST --contains--> COMMIT
                    add_relationship(
                        source_id=pr_id,
                        target_id=commit_entity_id,
                        rel_type=RelationshipType.CONTAINS,
                        metadata={"repository": repo},
                        source_record_id=item.id,
                    )

            # Handle Commit
            elif kind == "commit" or "commit" in item.source_url:
                sha = str(meta.get("sha", item.source_id))
                commit_id = f"commit:{repo}:{sha}"
                commit_name = item.title or f"Commit {sha[:8]}"

                add_entity(
                    Entity(
                        id=commit_id,
                        entity_type=EntityType.COMMIT.value,
                        name=commit_name,
                        source_record_id=item.id,
                        metadata={
                            "repository": repo,
                            "sha": sha,
                            "url": item.source_url,
                        },
                        created_at=item.created_at,
                    )
                )

                # Author of commit -> EMPLOYEE
                author_dict = meta.get("author") if isinstance(meta.get("author"), dict) else {}
                author_login = item.author_id or author_dict.get("login")
                if author_login:
                    employee_id = f"employee:{author_login}"
                    emp_name = author_dict.get("name") or author_login
                    add_entity(
                        Entity(
                            id=employee_id,
                            entity_type=EntityType.EMPLOYEE.value,
                            name=emp_name,
                            source_record_id=None,
                            metadata={
                                "login": author_login,
                                "name": emp_name,
                                "email": author_dict.get("email"),
                            },
                            created_at=item.created_at,
                        )
                    )
                    # Canonical: COMMIT --authored_by--> EMPLOYEE
                    add_relationship(
                        source_id=commit_id,
                        target_id=employee_id,
                        rel_type=RelationshipType.AUTHORED_BY,
                        metadata={"repository": repo, "sha": sha},
                        source_record_id=item.id,
                    )

                # Extract referenced tickets in commit
                combined_text = f"{item.title or ''} {item.raw_content}"
                tickets = sorted(list(set(meta.get("ticket_ids", []) + extract_ticket_ids(combined_text))))
                for tid in tickets:
                    commits_by_ticket.setdefault((repo, tid), []).append(commit_id)

                # Check if commit message references PR
                for pr_match in PR_PATTERN.findall(item.raw_content):
                    pr_id = f"pr:{repo}:{pr_match}"
                    # Canonical: PULL_REQUEST --contains--> COMMIT
                    add_relationship(
                        source_id=pr_id,
                        target_id=commit_id,
                        rel_type=RelationshipType.CONTAINS,
                        metadata={"repository": repo},
                        source_record_id=item.id,
                    )

        # -------------------------------------------------------------------
        # 2. Slack Threads
        # -------------------------------------------------------------------
        elif item.source_type == SourceType.SLACK:
            channel_id = meta.get("channel_id", "unknown-channel")
            channel_name = meta.get("channel_name", channel_id)
            thread_ts = meta.get("thread_ts", item.source_id)
            thread_id = f"slack:{channel_id}:{thread_ts}"
            thread_name = item.title or f"Slack #{channel_name} ({thread_ts})"

            add_entity(
                Entity(
                    id=thread_id,
                    entity_type=EntityType.SLACK_THREAD.value,
                    name=thread_name,
                    source_record_id=item.id,
                    metadata={
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "thread_ts": thread_ts,
                        "url": item.source_url,
                    },
                    created_at=item.created_at,
                )
            )

            # Extract referenced tickets in Slack conversation
            combined_text = f"{item.title or ''} {item.raw_content}"
            tickets = sorted(list(set(meta.get("ticket_ids", []) + extract_ticket_ids(combined_text))))
            for tid in tickets:
                ticket_id = f"ticket:{tid}"
                add_entity(
                    Entity(
                        id=ticket_id,
                        entity_type=EntityType.TICKET.value,
                        name=tid,
                        source_record_id=None,
                        metadata={"ticket_id": tid},
                        created_at=item.created_at,
                    )
                )
                # Canonical: TICKET --discussed_in--> SLACK_THREAD
                add_relationship(
                    source_id=ticket_id,
                    target_id=thread_id,
                    rel_type=RelationshipType.DISCUSSED_IN,
                    metadata={"channel_id": channel_id, "thread_ts": thread_ts},
                    source_record_id=item.id,
                )

    # -----------------------------------------------------------------------
    # 3. Cross-record correlation: Link PR and Commits sharing the same ticket
    # -----------------------------------------------------------------------
    for (repo, tid), pr_list in prs_by_ticket.items():
        if (repo, tid) in commits_by_ticket:
            for pr_id in pr_list:
                for commit_id in commits_by_ticket[(repo, tid)]:
                    # Canonical: PULL_REQUEST --contains--> COMMIT
                    add_relationship(
                        source_id=pr_id,
                        target_id=commit_id,
                        rel_type=RelationshipType.CONTAINS,
                        metadata={"repository": repo, "ticket_id": tid},
                    )

    logger.info(
        "extracted_graph_entities_and_relationships entities=%d relationships=%d",
        len(entities),
        len(relationships),
    )
    return list(entities.values()), list(relationships.values())
