"""Repository layer for persisting canonical knowledge, vectors, ACLs, and sync state."""

import json
import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.chunking.models import CanonicalChunk
from app.common.config import get_settings
from app.connectors.common.models import AclReference, RawSourceItem
from app.contracts.rag_search import RagSearchResultItem
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.models import SyncStateRecord
from app.normalization.models import CanonicalDocument
from app.security.acl import build_acl_where_clause, has_read_permission

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(Exception):
    """Raised when PostgreSQL / pgvector service is unreachable or connection fails."""


class FencedSyncError(Exception):
    """Raised when a sync operation is rejected because a lease is invalid or expired."""


@dataclass
class ClaimResult:
    """Result of claiming an exclusive synchronization lease."""

    source_type: str
    cursor_value: Optional[str]
    lease_token: str


INTRINSIC_RELATIONSHIP_METADATA_ALLOWLIST = {
    "repository", "pr_number", "sha", "channel_id", "thread_ts", "ticket_id"
}


def derive_canonical_metadata(
    source_entity_id: str, target_entity_id: str, rel_type: str
) -> Dict[str, Any]:
    """Derive non-sensitive structural properties from validated endpoint IDs.

    Uses reverse-splitting to handle colons in repository names unambiguously.
    """
    canonical: Dict[str, Any] = {}
    norm_rel = rel_type.lower().strip()

    if norm_rel == RelationshipType.IMPLEMENTED_BY.value:
        # TICKET (source) -> PR (target)
        # ticket:<ticket_id> -> pr:<repo>:<pr_num>
        if ":" in source_entity_id:
            canonical["ticket_id"] = source_entity_id.split(":", 1)[1]
        if target_entity_id.startswith("pr:"):
            prefix, pr_num = target_entity_id.rsplit(":", 1)
            repo = prefix[len("pr:"):]
            canonical["repository"] = repo
            canonical["pr_number"] = pr_num

    elif norm_rel == RelationshipType.CONTAINS.value:
        # PULL_REQUEST (source) -> COMMIT (target)
        # pr:<repo>:<pr_num> -> commit:<repo>:<sha>
        if source_entity_id.startswith("pr:"):
            prefix, pr_num = source_entity_id.rsplit(":", 1)
            repo = prefix[len("pr:"):]
            canonical["repository"] = repo
            canonical["pr_number"] = pr_num
        if target_entity_id.startswith("commit:"):
            prefix, sha = target_entity_id.rsplit(":", 1)
            repo = prefix[len("commit:"):]
            canonical["repository"] = repo
            canonical["sha"] = sha

    elif norm_rel == RelationshipType.AUTHORED_BY.value:
        # COMMIT (source) -> EMPLOYEE (target)
        # commit:<repo>:<sha> -> employee:<login>
        if source_entity_id.startswith("commit:"):
            prefix, sha = source_entity_id.rsplit(":", 1)
            repo = prefix[len("commit:"):]
            canonical["repository"] = repo
            canonical["sha"] = sha

    elif norm_rel == RelationshipType.DISCUSSED_IN.value:
        # TICKET (source) -> SLACK_THREAD (target)
        # ticket:<ticket_id> -> slack:<channel_id>:<thread_ts>
        if ":" in source_entity_id:
            canonical["ticket_id"] = source_entity_id.split(":", 1)[1]
        if target_entity_id.startswith("slack:"):
            prefix, thread_ts = target_entity_id.rsplit(":", 1)
            chan_id = prefix[len("slack:"):]
            canonical["channel_id"] = chan_id
            canonical["thread_ts"] = thread_ts

    return canonical


class KnowledgeRepository(ABC):
    """Abstract persistence layer for knowledge records and vector chunks."""

    @abstractmethod
    def get_sync_state(self, source_type: str) -> Optional[SyncStateRecord]: ...

    @abstractmethod
    def update_sync_state(self, state: SyncStateRecord) -> None: ...

    @abstractmethod
    def claim_sync(
        self, source_type: str, lease_token: str, lease_ttl_seconds: int = 300
    ) -> Optional[ClaimResult]: ...

    @abstractmethod
    def renew_lease(
        self, source_type: str, lease_token: str, lease_ttl_seconds: int = 300
    ) -> bool: ...

    @abstractmethod
    def complete_sync(
        self, source_type: str, lease_token: str, final_cursor: Optional[str] = None
    ) -> None: ...

    @abstractmethod
    def fail_sync(
        self, source_type: str, lease_token: str, error_message: str
    ) -> None: ...

    @abstractmethod
    def persist_sync_batch(
        self,
        source_type: str,
        lease_token: str,
        next_cursor: Optional[str],
        items: List[RawSourceItem],
        docs: List[CanonicalDocument],
        chunks: List[CanonicalChunk],
        acls: List[AclReference],
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> None: ...

    @abstractmethod
    def save_source_records(self, items: List[RawSourceItem]) -> None: ...

    @abstractmethod
    def save_documents(self, docs: List[CanonicalDocument]) -> None: ...

    @abstractmethod
    def save_chunks(self, chunks: List[CanonicalChunk]) -> None: ...

    @abstractmethod
    def save_acls(self, acls: List[AclReference]) -> None: ...

    @abstractmethod
    def save_entities(self, entities: List[Entity]) -> None: ...

    @abstractmethod
    def save_relationships(self, relationships: List[Relationship]) -> None: ...

    @abstractmethod
    def get_entity(
        self,
        entity_id: str,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> Optional[Entity]:
        """Retrieve an entity by ID if authorized. Returns None if denied or not found."""
        ...

    @abstractmethod
    def get_relationships_for_entity(
        self,
        entity_id: str,
        relationship_type: Optional[str] = None,
        direction: str = "OUTGOING",
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[Tuple[Relationship, Entity]]:
        """Retrieve single-hop relationships and neighbor entities for an authorized entity."""
        ...

    @abstractmethod
    def search_lexical(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Perform lexical (full-text) search over indexed chunks enforcing ACL filtering."""
        ...

    @abstractmethod
    def search_vector(
        self,
        query_embedding: List[float],
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Perform vector similarity search over indexed chunks enforcing ACL filtering."""
        ...

    @abstractmethod
    def record_audit_event(
        self,
        user_id: str,
        action: str,
        resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        """Persist an audit event."""
        ...

    @abstractmethod
    def get_audit_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent audit events ordered by timestamp descending."""
        ...

    @abstractmethod
    def count_audit_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> int:
        """Count total audit events matching optional filters."""
        ...

    @abstractmethod
    def check_health(self) -> bool:
        """Verify repository health / database connectivity."""
        ...


class InMemoryKnowledgeRepository(KnowledgeRepository):
    """In-memory repository used for fast, isolated unit and pipeline testing."""

    def __init__(self):
        self.sync_states: Dict[str, SyncStateRecord] = {}
        self.sync_state_metadata: Dict[str, Dict[str, Any]] = {}
        self.source_records: Dict[str, RawSourceItem] = {}
        self.documents: Dict[str, CanonicalDocument] = {}
        self.chunks: Dict[str, CanonicalChunk] = {}
        self.acls: List[AclReference] = []
        self.entities: Dict[str, Entity] = {}
        self.relationships: Dict[Tuple[str, str, str], Relationship] = {}
        self.relationship_owners: Dict[Tuple[str, str, str], Set[str]] = {}
        self.audit_events: List[Dict[str, Any]] = []

    def check_health(self) -> bool:
        return True

    def get_sync_state(self, source_type: str) -> Optional[SyncStateRecord]:
        state = self.sync_states.get(source_type)
        if state:
            object.__setattr__(state, "metadata", self.sync_state_metadata.get(source_type, {}))
        return state

    def update_sync_state(self, state: SyncStateRecord) -> None:
        self.sync_states[state.source_type] = state
        if hasattr(state, "metadata") and isinstance(state.metadata, dict):
            self.sync_state_metadata[state.source_type] = state.metadata

    def claim_sync(
        self, source_type: str, lease_token: str, lease_ttl_seconds: int = 300
    ) -> Optional[ClaimResult]:
        now = datetime.now(timezone.utc)
        state = self.sync_states.get(source_type)
        meta = self.sync_state_metadata.get(source_type, {})
        if state:
            is_expired = False
            expires_at_str = meta.get("lease_expires_at")
            if expires_at_str:
                try:
                    exp = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                    if exp <= now:
                        is_expired = True
                except Exception:
                    is_expired = True
            else:
                started = state.last_sync_started_at
                if started and (now - started).total_seconds() > lease_ttl_seconds:
                    is_expired = True

            if state.status == "SYNCING" and not is_expired:
                return None

            new_expires = (now + timedelta(seconds=lease_ttl_seconds)).isoformat()
            state.status = "SYNCING"
            state.last_sync_started_at = now
            state.records_synced_last_run = 0
            state.error_message = None
            object.__setattr__(state, "updated_at", now)
            meta["lease_token"] = lease_token
            meta["lease_expires_at"] = new_expires
            self.sync_state_metadata[source_type] = meta
            object.__setattr__(state, "metadata", meta)
            return ClaimResult(
                source_type=source_type,
                cursor_value=state.cursor_value,
                lease_token=lease_token,
            )
        else:
            new_expires = (now + timedelta(seconds=lease_ttl_seconds)).isoformat()
            new_meta = {
                "lease_token": lease_token,
                "lease_expires_at": new_expires,
            }
            new_state = SyncStateRecord(
                source_type=source_type,
                cursor_value=None,
                status="SYNCING",
                last_sync_started_at=now,
                records_synced_last_run=0,
                error_message=None,
            )
            object.__setattr__(new_state, "metadata", new_meta)
            self.sync_states[source_type] = new_state
            self.sync_state_metadata[source_type] = new_meta
            return ClaimResult(
                source_type=source_type,
                cursor_value=None,
                lease_token=lease_token,
            )

    def renew_lease(
        self, source_type: str, lease_token: str, lease_ttl_seconds: int = 300
    ) -> bool:
        now = datetime.now(timezone.utc)
        meta = self.sync_state_metadata.get(source_type, {})
        if meta.get("lease_token") != lease_token:
            return False
        expires_at_str = meta.get("lease_expires_at")
        if expires_at_str:
            try:
                exp = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if exp <= now:
                    return False
            except Exception:
                return False
        new_expires = (now + timedelta(seconds=lease_ttl_seconds)).isoformat()
        meta["lease_expires_at"] = new_expires
        state = self.sync_states.get(source_type)
        if state:
            object.__setattr__(state, "metadata", meta)
            object.__setattr__(state, "updated_at", now)
        return True

    def complete_sync(
        self, source_type: str, lease_token: str, final_cursor: Optional[str] = None
    ) -> None:
        now = datetime.now(timezone.utc)
        state = self.sync_states.get(source_type)
        if not state:
            raise FencedSyncError(f"No sync state found for {source_type}")
        meta = self.sync_state_metadata.get(source_type, {})
        if meta.get("lease_token") != lease_token:
            raise FencedSyncError(f"Worker fenced out for source {source_type}")
        expires_at_str = meta.get("lease_expires_at")
        if expires_at_str:
            try:
                exp = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if exp <= now:
                    raise FencedSyncError(f"Lease expired for source {source_type}")
            except FencedSyncError:
                raise
            except Exception:
                raise FencedSyncError(f"Lease malformed for source {source_type}")
        state.status = "SUCCESS"
        state.last_sync_completed_at = now
        state.error_message = None
        object.__setattr__(state, "updated_at", now)
        if final_cursor is not None:
            state.cursor_value = final_cursor

    def fail_sync(
        self, source_type: str, lease_token: str, error_message: str
    ) -> None:
        now = datetime.now(timezone.utc)
        state = self.sync_states.get(source_type)
        if not state:
            return
        meta = self.sync_state_metadata.get(source_type, {})
        if meta.get("lease_token") != lease_token:
            return
        state.status = "FAILED"
        state.error_message = error_message
        object.__setattr__(state, "updated_at", now)

    def persist_sync_batch(
        self,
        source_type: str,
        lease_token: str,
        next_cursor: Optional[str],
        items: List[RawSourceItem],
        docs: List[CanonicalDocument],
        chunks: List[CanonicalChunk],
        acls: List[AclReference],
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> None:
        now = datetime.now(timezone.utc)
        state = self.sync_states.get(source_type)
        if not state:
            raise FencedSyncError(f"No sync state found for {source_type}")
        meta = self.sync_state_metadata.get(source_type, {})
        if meta.get("lease_token") != lease_token:
            raise FencedSyncError(f"Worker fenced out for source {source_type}")
        expires_at_str = meta.get("lease_expires_at")
        if expires_at_str:
            try:
                exp = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if exp <= now:
                    raise FencedSyncError(f"Lease expired for source {source_type}")
            except FencedSyncError:
                raise
            except Exception:
                raise FencedSyncError(f"Lease malformed for source {source_type}")

        item_ids = {item.id for item in items}

        # 1. Stale documents & chunks cleanup for no-document replay
        stored_doc_ids = {d.id for d in self.documents.values() if d.source_record_id in item_ids}
        new_doc_ids = {d.id for d in docs}
        stale_doc_ids = stored_doc_ids - new_doc_ids
        if stale_doc_ids:
            self.chunks = {cid: c for cid, c in self.chunks.items() if c.document_id not in stale_doc_ids}
            for sdid in stale_doc_ids:
                self.documents.pop(sdid, None)

        # 2. Save source records & docs
        self.save_source_records(items)
        self.save_documents(docs)

        # 3. Scoped chunk cleanup & replacement
        self.chunks = {cid: c for cid, c in self.chunks.items() if c.document_id not in new_doc_ids}
        self.save_chunks(chunks)

        # 4. Scoped ACL replacement
        self.acls = [
            a for a in self.acls
            if not (a.resource_type == "SOURCE_RECORD" and a.resource_id in item_ids)
        ]
        self.save_acls(acls)

        # 5. Entities validation & saving
        self.save_entities(entities)

        # 6. Scoped relationship ownership replacement and immutable upsert
        if item_ids:
            affected_keys = [
                k for k, owners in self.relationship_owners.items()
                if any(iid in owners for iid in item_ids)
            ]
            for k in affected_keys:
                self.relationship_owners[k].difference_update(item_ids)
                if not self.relationship_owners[k]:
                    self.relationship_owners.pop(k, None)
                    self.relationships.pop(k, None)

        for rel in relationships:
            key = (rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
            canonical_meta = derive_canonical_metadata(rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
            # Verify incoming rel.metadata vs canonical
            for k, v in canonical_meta.items():
                if k in rel.metadata and str(rel.metadata[k]) != str(v):
                    raise ValueError(
                        f"Metadata conflict for relationship {key}: key '{k}' has conflicting values '{rel.metadata[k]}' vs '{v}'"
                    )

            if key in self.relationships:
                existing = self.relationships[key]
                for k, v in canonical_meta.items():
                    if k in existing.metadata and str(existing.metadata[k]) != str(v):
                        raise ValueError(
                            f"Stored relationship metadata conflict for {key}: stored '{k}'='{existing.metadata[k]}' != canonical '{v}'"
                        )
            else:
                stored_meta = {k: v for k, v in canonical_meta.items() if k in INTRINSIC_RELATIONSHIP_METADATA_ALLOWLIST}
                self.relationships[key] = Relationship(
                    source_entity_id=rel.source_entity_id,
                    target_entity_id=rel.target_entity_id,
                    relationship_type=rel.relationship_type,
                    metadata=stored_meta,
                    created_at=rel.created_at,
                )

            owners = set()
            if "source_record_id" in rel.metadata and rel.metadata["source_record_id"]:
                owners.add(rel.metadata["source_record_id"])
            if "source_record_ids" in rel.metadata and isinstance(rel.metadata["source_record_ids"], list):
                owners.update(rel.metadata["source_record_ids"])
            if owners:
                self.relationship_owners.setdefault(key, set()).update(owners)

        # 7. Advance checkpoint inside batch; status stays SYNCING
        state.status = "SYNCING"
        state.cursor_value = next_cursor
        state.records_synced_last_run = (state.records_synced_last_run or 0) + len(items)
        object.__setattr__(state, "updated_at", now)

    def save_source_records(self, items: List[RawSourceItem]) -> None:
        for item in items:
            self.source_records[item.id] = item

    def save_documents(self, docs: List[CanonicalDocument]) -> None:
        for doc in docs:
            self.documents[doc.id] = doc

    def save_chunks(self, chunks: List[CanonicalChunk]) -> None:
        for chunk in chunks:
            self.chunks[chunk.id] = chunk

    def save_acls(self, acls: List[AclReference]) -> None:
        self.acls.extend(acls)

    def save_entities(self, entities: List[Entity]) -> None:
        if not entities:
            return

        batch_anchors: Dict[str, Optional[str]] = {}

        # 1. Pre-validation pass: full validation before any state modification
        for entity in entities:
            # Invariant 1: TICKET and EMPLOYEE must always have source_record_id = None
            if entity.entity_type in {EntityType.TICKET.value, EntityType.EMPLOYEE.value}:
                entity.source_record_id = None
            elif entity.source_record_id is None:
                raise ValueError(
                    f"Anchored entity '{entity.id}' of type '{entity.entity_type}' requires a non-null source_record_id"
                )

            # Invariant 2: Detect conflicting non-null source_record_id within batch
            if entity.id in batch_anchors:
                if batch_anchors[entity.id] != entity.source_record_id:
                    raise ValueError(
                        f"Provenance conflict within batch for entity '{entity.id}': "
                        f"'{batch_anchors[entity.id]}' vs '{entity.source_record_id}'"
                    )
            else:
                batch_anchors[entity.id] = entity.source_record_id

            # Invariant 3: Detect conflicting non-null source_record_id against existing persisted state
            existing = self.entities.get(entity.id)
            if existing is not None:
                if existing.source_record_id != entity.source_record_id:
                    raise ValueError(
                        f"Provenance conflict for entity '{entity.id}': "
                        f"existing source_record_id='{existing.source_record_id}', "
                        f"incoming source_record_id='{entity.source_record_id}'"
                    )

        # 2. State mutation pass: only reached if the entire batch passed validation
        for entity in entities:
            existing = self.entities.get(entity.id)
            if existing:
                existing.name = entity.name
                existing.metadata = {**existing.metadata, **entity.metadata}
            else:
                self.entities[entity.id] = entity

    def save_relationships(self, relationships: List[Relationship]) -> None:
        for rel in relationships:
            key = (rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
            canonical_meta = derive_canonical_metadata(rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
            for k, v in canonical_meta.items():
                if k in rel.metadata and str(rel.metadata[k]) != str(v):
                    raise ValueError(
                        f"Metadata conflict for relationship {key}: key '{k}' has conflicting values '{rel.metadata[k]}' vs '{v}'"
                    )

            if key in self.relationships:
                existing = self.relationships[key]
                for k, v in canonical_meta.items():
                    if k in existing.metadata and str(existing.metadata[k]) != str(v):
                        raise ValueError(
                            f"Stored relationship metadata conflict for {key}: stored '{k}'='{existing.metadata[k]}' != canonical '{v}'"
                        )
            else:
                stored_meta = {k: v for k, v in canonical_meta.items() if k in INTRINSIC_RELATIONSHIP_METADATA_ALLOWLIST}
                self.relationships[key] = Relationship(
                    source_entity_id=rel.source_entity_id,
                    target_entity_id=rel.target_entity_id,
                    relationship_type=rel.relationship_type,
                    metadata=stored_meta,
                    created_at=rel.created_at,
                )

            owners = set()
            if "source_record_id" in rel.metadata and rel.metadata["source_record_id"]:
                owners.add(rel.metadata["source_record_id"])
            if "source_record_ids" in rel.metadata and isinstance(rel.metadata["source_record_ids"], list):
                owners.update(rel.metadata["source_record_ids"])
            # Fallback for documented extraction rules if neither source_record_id nor source_record_ids is given:
            if not owners:
                if rel.relationship_type == RelationshipType.IMPLEMENTED_BY.value:
                    target_ent = self.entities.get(rel.target_entity_id)
                    if target_ent and target_ent.source_record_id:
                        owners.add(target_ent.source_record_id)
                elif rel.relationship_type == RelationshipType.DISCUSSED_IN.value:
                    target_ent = self.entities.get(rel.target_entity_id)
                    if target_ent and target_ent.source_record_id:
                        owners.add(target_ent.source_record_id)
                elif rel.relationship_type == RelationshipType.AUTHORED_BY.value:
                    source_ent = self.entities.get(rel.source_entity_id)
                    if source_ent and source_ent.source_record_id:
                        owners.add(source_ent.source_record_id)
                elif rel.relationship_type == RelationshipType.CONTAINS.value:
                    source_ent = self.entities.get(rel.source_entity_id)
                    if source_ent and source_ent.source_record_id:
                        owners.add(source_ent.source_record_id)

            if owners:
                self.relationship_owners.setdefault(key, set()).update(owners)

    def get_entity(
        self,
        entity_id: str,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> Optional[Entity]:
        entity = self.entities.get(entity_id)
        if not entity:
            return None

        # Branch 1: Direct primary anchor authorization
        is_direct_auth = False
        if entity.source_record_id is not None:
            anchor_acls = [
                a for a in self.acls
                if a.resource_type == "SOURCE_RECORD" and a.resource_id == entity.source_record_id
            ]
            is_direct_auth = has_read_permission(anchor_acls, user_id=user_id, group_ids=group_ids)
            if is_direct_auth:
                return entity

        # Branch 2: Supporting relationship provenance authorization
        is_rel_auth = False
        for rel_key, rel in self.relationships.items():
            if rel.source_entity_id == entity_id or rel.target_entity_id == entity_id:
                owner_ids = self.relationship_owners.get(rel_key, set())
                for oid in owner_ids:
                    rel_acls = [
                        a for a in self.acls
                        if a.resource_type == "SOURCE_RECORD" and a.resource_id == oid
                    ]
                    if has_read_permission(rel_acls, user_id=user_id, group_ids=group_ids):
                        is_rel_auth = True
                        break
                if is_rel_auth:
                    break

        if not is_rel_auth:
            return None  # Denied by default

        # Authorized ONLY via relationship provenance:
        # Redact private anchor identifier and private metadata
        safe_meta = {
            k: v for k, v in entity.metadata.items()
            if k in {"repository", "number", "sha", "channel_id", "thread_ts", "ticket_id"}
        }
        return entity.model_copy(update={
            "source_record_id": None,
            "metadata": safe_meta,
        })

    def get_relationships_for_entity(
        self,
        entity_id: str,
        relationship_type: Optional[str] = None,
        direction: str = "OUTGOING",
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[Tuple[Relationship, Entity]]:
        norm_dir = direction.upper().strip()
        if norm_dir not in {"OUTGOING", "INCOMING", "BOTH"}:
            raise ValueError(f"Invalid traversal direction '{direction}': must be OUTGOING, INCOMING, or BOTH")

        # 1. Starting entity must be authorized
        start_entity = self.get_entity(entity_id, user_id=user_id, group_ids=group_ids)
        if not start_entity:
            return []

        results: List[Tuple[Relationship, Entity]] = []

        for rel_key, rel in self.relationships.items():
            if relationship_type and rel.relationship_type != relationship_type:
                continue

            neighbor_id = None
            if norm_dir == "OUTGOING":
                if rel.source_entity_id == entity_id:
                    neighbor_id = rel.target_entity_id
            elif norm_dir == "INCOMING":
                if rel.target_entity_id == entity_id:
                    neighbor_id = rel.source_entity_id
            elif norm_dir == "BOTH":
                if rel.source_entity_id == entity_id:
                    neighbor_id = rel.target_entity_id
                elif rel.target_entity_id == entity_id:
                    neighbor_id = rel.source_entity_id

            if not neighbor_id:
                continue

            # 2. Relationship must have at least one readable owner in relationship_owners
            owner_ids = self.relationship_owners.get(rel_key, set())
            if not owner_ids:
                continue  # Unowned legacy edge: strictly hidden

            has_rel_access = any(
                has_read_permission(
                    [a for a in self.acls if a.resource_type == "SOURCE_RECORD" and a.resource_id == oid],
                    user_id=user_id,
                    group_ids=group_ids,
                )
                for oid in owner_ids
            )
            if not has_rel_access:
                continue

            # 3. Neighbor entity visibility & projection
            raw_neighbor = self.entities.get(neighbor_id)
            if not raw_neighbor:
                continue

            direct_neighbor_auth = False
            if raw_neighbor.source_record_id is not None:
                n_acls = [
                    a for a in self.acls
                    if a.resource_type == "SOURCE_RECORD" and a.resource_id == raw_neighbor.source_record_id
                ]
                direct_neighbor_auth = has_read_permission(n_acls, user_id=user_id, group_ids=group_ids)

            if direct_neighbor_auth:
                neighbor_entity = raw_neighbor
            else:
                # Neighbor visibility established through this authorized supporting relationship!
                # Redact primary anchor and isolate metadata strictly to safe structural fields
                canonical_rel_meta = derive_canonical_metadata(rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
                safe_neighbor_meta = {
                    k: v for k, v in raw_neighbor.metadata.items()
                    if k in {"repository", "number", "sha", "channel_id", "thread_ts", "ticket_id"} and (k in canonical_rel_meta or k == "number")
                }
                neighbor_entity = raw_neighbor.model_copy(update={
                    "source_record_id": None,
                    "metadata": safe_neighbor_meta,
                })

            results.append((rel, neighbor_entity))

        results.sort(key=lambda x: (x[0].relationship_type, x[1].id))
        return results

    def _get_applicable_acls(self, chunk: CanonicalChunk, doc: CanonicalDocument) -> List[AclReference]:
        acls: List[AclReference] = []
        for acl in self.acls:
            if acl.resource_type == "SOURCE_RECORD" and acl.resource_id == doc.source_record_id:
                acls.append(acl)
            elif acl.resource_type == "DOCUMENT" and acl.resource_id == doc.id:
                acls.append(acl)
            elif acl.resource_type == "CHUNK" and acl.resource_id == chunk.id:
                acls.append(acl)
        if chunk.acl_references:
            acls.extend(chunk.acl_references)
        if doc.acl_references:
            acls.extend(doc.acl_references)
        return acls

    def search_lexical(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        if not query or not query.strip():
            return []

        cleaned_query = query.strip()
        query_lower = cleaned_query.lower()
        tokens = [t.lower() for t in re.findall(r"\b[\w-]+\b", cleaned_query) if len(t) > 1]
        if not tokens:
            tokens = [query_lower]

        scored_items = []
        for chunk in self.chunks.values():
            doc = self.documents.get(chunk.document_id)
            if not doc:
                continue

            # ACL permission filtering (AD-04) - applied before scoring and candidate limits
            chunk_acls = self._get_applicable_acls(chunk, doc)
            if not has_read_permission(chunk_acls, user_id=user_id, group_ids=group_ids):
                continue

            # Filter by source_types if specified
            if source_types:
                normalized_types = [st.upper() for st in source_types]
                if doc.source_type.upper() not in normalized_types:
                    continue

            content_lower = chunk.content.lower()
            title_lower = (doc.title or "").lower()

            exact_match = query_lower in content_lower
            matched_content_tokens = [t for t in tokens if t in content_lower]
            matched_title_tokens = [t for t in tokens if t in title_lower]

            if not exact_match and not matched_content_tokens and not matched_title_tokens:
                continue

            # Score computation:
            # 1. Token coverage (what fraction of query terms matched)
            coverage = len(matched_content_tokens) / len(tokens) if tokens else 0.0

            # 2. Token frequency in content and title
            freq_count = sum(content_lower.count(t) for t in matched_content_tokens)
            title_count = sum(title_lower.count(t) for t in matched_title_tokens)

            score = (coverage * 2.0) + (min(freq_count, 10) * 0.2) + (title_count * 0.5)
            if exact_match:
                score += 1.5

            snippet = self._build_snippet(chunk.content, tokens)

            item = RagSearchResultItem(
                chunk_id=chunk.id,
                document_id=doc.id,
                source_type=doc.source_type,
                title=doc.title or "",
                snippet=snippet,
                source_url=doc.url or "",
                author=doc.author,
                score=round(float(score), 4),
            )
            scored_items.append((score, chunk.created_at, chunk.id, item))

        scored_items.sort(key=lambda x: (-x[0], x[1], x[2]))
        return [x[3] for x in scored_items[:limit]]

    def _build_snippet(self, content: str, query_terms: List[str], max_len: int = 300) -> str:
        if len(content) <= max_len:
            return content
        lower_content = content.lower()
        first_pos = -1
        for term in query_terms:
            pos = lower_content.find(term.lower())
            if pos != -1 and (first_pos == -1 or pos < first_pos):
                first_pos = pos

        if first_pos == -1 or first_pos < 40:
            return content[:max_len].strip() + "..."

        start = max(0, first_pos - 40)
        end = min(len(content), start + max_len)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return prefix + content[start:end].strip() + suffix

    def search_vector(
        self,
        query_embedding: List[float],
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        expected_dim = get_settings().embedding_dimension
        if len(query_embedding) != expected_dim:
            raise ValueError(
                f"Query embedding dimension mismatch: expected {expected_dim}, got {len(query_embedding)}"
            )

        q_norm = math.sqrt(sum(x * x for x in query_embedding))
        if q_norm == 0.0 or math.isclose(q_norm, 0.0, abs_tol=1e-12):
            return []

        normalized_types = [st.upper() for st in source_types] if source_types else None

        scored_items = []
        for chunk in self.chunks.values():
            if chunk.embedding is None:
                continue

            if len(chunk.embedding) != expected_dim:
                continue

            c_norm = math.sqrt(sum(x * x for x in chunk.embedding))
            if c_norm == 0.0 or math.isclose(c_norm, 0.0, abs_tol=1e-12):
                # Exclude zero chunk vectors
                continue

            doc = self.documents.get(chunk.document_id)
            if not doc:
                continue

            # ACL permission filtering (AD-04) - applied before scoring and candidate limits
            chunk_acls = self._get_applicable_acls(chunk, doc)
            if not has_read_permission(chunk_acls, user_id=user_id, group_ids=group_ids):
                continue

            if normalized_types and doc.source_type.upper() not in normalized_types:
                continue

            # Dot product
            dot = sum(q * c for q, c in zip(query_embedding, chunk.embedding))
            # Cosine similarity preserving full [-1.0, 1.0] range
            cosine_similarity = dot / (q_norm * c_norm)
            score = round(float(cosine_similarity), 4)

            snippet = chunk.content[:300].strip() + ("..." if len(chunk.content) > 300 else "")

            item = RagSearchResultItem(
                chunk_id=chunk.id,
                document_id=doc.id,
                source_type=doc.source_type,
                title=doc.title or "",
                snippet=snippet,
                source_url=doc.url or "",
                author=doc.author,
                score=score,
            )
            scored_items.append((score, chunk.created_at, chunk.id, item))

        # Order descending by similarity score, tie-break by creation date and id
        scored_items.sort(key=lambda x: (-x[0], x[1], x[2]))
        return [x[3] for x in scored_items[:limit]]

    def record_audit_event(
        self,
        user_id: str,
        action: str,
        resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        event = {
            "id": len(self.audit_events) + 1,
            "userId": user_id,
            "action": action,
            "resource": resource,
            "details": details or {},
            "ipAddress": ip_address,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.audit_events.append(event)

    def _filtered_audit_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        filtered = self.audit_events
        if user_id:
            filtered = [e for e in filtered if e.get("userId") == user_id]
        if action:
            filtered = [e for e in filtered if e.get("action") == action]
        return filtered

    def get_audit_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        filtered = self._filtered_audit_events(user_id=user_id, action=action)
        sorted_events = sorted(filtered, key=lambda e: e.get("timestamp", ""), reverse=True)
        return sorted_events[offset : offset + limit]

    def count_audit_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> int:
        return len(self._filtered_audit_events(user_id=user_id, action=action))


class PostgresKnowledgeRepository(KnowledgeRepository):
    """PostgreSQL + pgvector implementation using psycopg."""

    def __init__(self, connection_url: str):
        self.connection_url = connection_url

    def _get_connection(self):
        import psycopg
        from pgvector.psycopg import register_vector

        try:
            conn = psycopg.connect(self.connection_url)
            register_vector(conn)
            return conn
        except (psycopg.OperationalError, psycopg.DatabaseError, ConnectionError, OSError) as e:
            logger.error("postgres_connection_failed url=%s err=%s", self.connection_url, e)
            raise DatabaseUnavailableError(f"Database connection failed: {e}") from e

    def check_health(self) -> bool:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True

    def get_sync_state(self, source_type: str) -> Optional[SyncStateRecord]:
        query = """
            SELECT source_type, cursor_value, status, last_sync_started_at,
                   last_sync_completed_at, records_synced_last_run, error_message, metadata
            FROM sync_state WHERE source_type = %s;
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (source_type,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    record = SyncStateRecord(
                        source_type=row[0],
                        cursor_value=row[1],
                        status=row[2],
                        last_sync_started_at=row[3],
                        last_sync_completed_at=row[4],
                        records_synced_last_run=row[5],
                        error_message=row[6],
                    )
                    meta = row[7] if len(row) > 7 and row[7] else {}
                    object.__setattr__(record, "metadata", meta if isinstance(meta, dict) else json.loads(meta or "{}"))
                    return record
        except Exception as e:
            logger.error("get_sync_state_failed source_type=%s err=%s", source_type, e)
            return None

    def update_sync_state(self, state: SyncStateRecord) -> None:
        query = """
            INSERT INTO sync_state (
                source_type, cursor_value, status, last_sync_started_at,
                last_sync_completed_at, records_synced_last_run, error_message, metadata, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (source_type) DO UPDATE SET
                cursor_value = EXCLUDED.cursor_value,
                status = EXCLUDED.status,
                last_sync_started_at = EXCLUDED.last_sync_started_at,
                last_sync_completed_at = EXCLUDED.last_sync_completed_at,
                records_synced_last_run = EXCLUDED.records_synced_last_run,
                error_message = EXCLUDED.error_message,
                metadata = EXCLUDED.metadata,
                updated_at = CURRENT_TIMESTAMP;
        """
        state_meta = getattr(state, "metadata", {}) or {}
        meta_json = json.dumps(state_meta) if isinstance(state_meta, dict) else str(state_meta)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        state.source_type,
                        state.cursor_value,
                        state.status,
                        state.last_sync_started_at,
                        state.last_sync_completed_at,
                        state.records_synced_last_run,
                        state.error_message,
                        meta_json,
                    ),
                )
            conn.commit()

    def claim_sync(
        self, source_type: str, lease_token: str, lease_ttl_seconds: int = 300
    ) -> Optional[ClaimResult]:
        query = """
            INSERT INTO sync_state (
                source_type, cursor_value, status, last_sync_started_at, records_synced_last_run, metadata, updated_at
            )
            VALUES (
                %s, NULL, 'SYNCING', clock_timestamp(), 0,
                jsonb_build_object(
                    'lease_token', %s::text,
                    'lease_expires_at', to_jsonb((clock_timestamp() + (%s || ' seconds')::interval)::text)
                ),
                clock_timestamp()
            )
            ON CONFLICT (source_type) DO UPDATE SET
                status = 'SYNCING',
                last_sync_started_at = clock_timestamp(),
                records_synced_last_run = 0,
                metadata = jsonb_build_object(
                    'lease_token', EXCLUDED.metadata->>'lease_token',
                    'lease_expires_at', to_jsonb((clock_timestamp() + (%s || ' seconds')::interval)::text)
                ),
                updated_at = clock_timestamp()
            WHERE sync_state.status != 'SYNCING' 
               OR COALESCE(
                    CASE 
                        WHEN sync_state.metadata->>'lease_expires_at' IS NOT NULL 
                         AND pg_input_is_valid(sync_state.metadata->>'lease_expires_at', 'timestamptz')
                        THEN (sync_state.metadata->>'lease_expires_at')::timestamptz
                        ELSE NULL
                    END,
                    sync_state.last_sync_started_at + (%s || ' seconds')::interval,
                    sync_state.updated_at + (%s || ' seconds')::interval
                  ) < clock_timestamp()
            RETURNING source_type, cursor_value, metadata->>'lease_token';
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (
                            source_type,
                            lease_token,
                            str(lease_ttl_seconds),
                            str(lease_ttl_seconds),
                            str(lease_ttl_seconds),
                            str(lease_ttl_seconds),
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
                if row:
                    return ClaimResult(
                        source_type=row[0],
                        cursor_value=row[1],
                        lease_token=row[2],
                    )
                return None
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_claim_sync_failed source_type=%s err=%s", source_type, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def renew_lease(
        self, source_type: str, lease_token: str, lease_ttl_seconds: int = 300
    ) -> bool:
        query = """
            UPDATE sync_state
            SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{lease_expires_at}',
                    to_jsonb((clock_timestamp() + (%s || ' seconds')::interval)::text)
                ),
                updated_at = clock_timestamp()
            WHERE source_type = %s 
              AND metadata->>'lease_token' = %s
              AND (
                  CASE 
                      WHEN metadata->>'lease_expires_at' IS NOT NULL 
                       AND pg_input_is_valid(metadata->>'lease_expires_at', 'timestamptz')
                      THEN (metadata->>'lease_expires_at')::timestamptz
                      ELSE NULL
                  END > clock_timestamp()
              );
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (str(lease_ttl_seconds), source_type, lease_token))
                    success = cur.rowcount > 0
                conn.commit()
                return success
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_renew_lease_failed source_type=%s err=%s", source_type, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def complete_sync(
        self, source_type: str, lease_token: str, final_cursor: Optional[str] = None
    ) -> None:
        query = """
            UPDATE sync_state
            SET status = 'SUCCESS',
                last_sync_completed_at = clock_timestamp(),
                error_message = NULL,
                updated_at = clock_timestamp(),
                cursor_value = COALESCE(%s, cursor_value)
            WHERE source_type = %s 
              AND metadata->>'lease_token' = %s
              AND (
                  CASE 
                      WHEN metadata->>'lease_expires_at' IS NOT NULL 
                       AND pg_input_is_valid(metadata->>'lease_expires_at', 'timestamptz')
                      THEN (metadata->>'lease_expires_at')::timestamptz
                      ELSE NULL
                  END > clock_timestamp()
              );
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (final_cursor, source_type, lease_token))
                    if cur.rowcount == 0:
                        raise FencedSyncError(
                            f"Worker fenced out or lease expired for source {source_type}"
                        )
                conn.commit()
        except (DatabaseUnavailableError, FencedSyncError):
            raise
        except Exception as e:
            logger.error("postgres_complete_sync_failed source_type=%s err=%s", source_type, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def fail_sync(
        self, source_type: str, lease_token: str, error_message: str
    ) -> None:
        query = """
            UPDATE sync_state
            SET status = 'FAILED',
                error_message = %s,
                updated_at = clock_timestamp()
            WHERE source_type = %s 
              AND metadata->>'lease_token' = %s;
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (error_message, source_type, lease_token))
                conn.commit()
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_fail_sync_failed source_type=%s err=%s", source_type, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def persist_sync_batch(
        self,
        source_type: str,
        lease_token: str,
        next_cursor: Optional[str],
        items: List[RawSourceItem],
        docs: List[CanonicalDocument],
        chunks: List[CanonicalChunk],
        acls: List[AclReference],
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> None:
        try:
            with self._get_connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        # 1. Row lock on sync_state and lease check
                        cur.execute("""
                            SELECT metadata->>'lease_token',
                                   ((CASE 
                                       WHEN metadata->>'lease_expires_at' IS NOT NULL 
                                        AND pg_input_is_valid(metadata->>'lease_expires_at', 'timestamptz')
                                       THEN (metadata->>'lease_expires_at')::timestamptz
                                       ELSE NULL
                                     END) > clock_timestamp()) AS is_valid
                            FROM sync_state 
                            WHERE source_type = %s 
                            FOR UPDATE;
                        """, (source_type,))
                        row = cur.fetchone()
                        if not row or row[0] != lease_token or not row[1]:
                            raise FencedSyncError(f"Worker fenced out for source {source_type}")

                        item_ids = [item.id for item in items]

                        # 2. No-document replay cleanup:
                        if item_ids:
                            cur.execute("""
                                SELECT id FROM documents WHERE source_record_id = ANY(%s);
                            """, (item_ids,))
                            stored_doc_ids = [r[0] for r in cur.fetchall()]
                            new_doc_ids = [d.id for d in docs]
                            stale_doc_ids = list(set(stored_doc_ids) - set(new_doc_ids))
                            if stale_doc_ids:
                                cur.execute("DELETE FROM chunks WHERE document_id = ANY(%s);", (stale_doc_ids,))
                                cur.execute("DELETE FROM documents WHERE id = ANY(%s);", (stale_doc_ids,))

                        # 3. Save source records (insert/upsert)
                        for item in items:
                            cur.execute("""
                                INSERT INTO source_records (id, source_type, source_id, source_url, title, author_id, raw_content, metadata, created_at, updated_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO UPDATE SET
                                    source_url = EXCLUDED.source_url,
                                    title = EXCLUDED.title,
                                    author_id = EXCLUDED.author_id,
                                    raw_content = EXCLUDED.raw_content,
                                    metadata = EXCLUDED.metadata,
                                    updated_at = EXCLUDED.updated_at;
                            """, (
                                item.id,
                                item.source_type.value if hasattr(item.source_type, "value") else str(item.source_type),
                                item.source_id,
                                item.source_url,
                                item.title,
                                item.author_id,
                                item.raw_content,
                                json.dumps(item.metadata),
                                item.created_at,
                                item.updated_at,
                            ))

                        # 4. Save documents (insert/upsert)
                        for doc in docs:
                            cur.execute("""
                                INSERT INTO documents (
                                    id, source_record_id, source_type, title, content, author, url,
                                    metadata, created_at, updated_at
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (id) DO UPDATE SET
                                    title = EXCLUDED.title,
                                    content = EXCLUDED.content,
                                    author = EXCLUDED.author,
                                    metadata = EXCLUDED.metadata,
                                    updated_at = EXCLUDED.updated_at;
                            """, (
                                doc.id,
                                doc.source_record_id,
                                doc.source_type,
                                doc.title,
                                doc.content,
                                doc.author,
                                doc.url,
                                json.dumps(doc.metadata),
                                doc.created_at,
                                doc.updated_at,
                            ))

                        # 5. Scoped chunk cleanup and insert
                        batch_doc_ids = list(set(d.id for d in docs))
                        if batch_doc_ids:
                            cur.execute("DELETE FROM chunks WHERE document_id = ANY(%s);", (batch_doc_ids,))
                        for chunk in chunks:
                            if chunk.embedding is not None:
                                cur.execute("""
                                    INSERT INTO chunks (
                                        id, document_id, chunk_index, content, token_count,
                                        embedding, metadata, created_at
                                    ) VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s)
                                    ON CONFLICT (id) DO UPDATE SET
                                        content = EXCLUDED.content,
                                        token_count = EXCLUDED.token_count,
                                        embedding = EXCLUDED.embedding,
                                        metadata = EXCLUDED.metadata;
                                """, (
                                    chunk.id,
                                    chunk.document_id,
                                    chunk.chunk_index,
                                    chunk.content,
                                    chunk.token_count,
                                    chunk.embedding,
                                    json.dumps(chunk.metadata),
                                    chunk.created_at,
                                ))
                            else:
                                cur.execute("""
                                    INSERT INTO chunks (
                                        id, document_id, chunk_index, content, token_count,
                                        metadata, created_at
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (id) DO UPDATE SET
                                        content = EXCLUDED.content,
                                        token_count = EXCLUDED.token_count,
                                        metadata = EXCLUDED.metadata;
                                """, (
                                    chunk.id,
                                    chunk.document_id,
                                    chunk.chunk_index,
                                    chunk.content,
                                    chunk.token_count,
                                    json.dumps(chunk.metadata),
                                    chunk.created_at,
                                ))

                        # 6. Scoped ACL replacement
                        if item_ids:
                            cur.execute("""
                                DELETE FROM acl_references 
                                WHERE resource_type = 'SOURCE_RECORD' AND resource_id = ANY(%s);
                            """, (item_ids,))
                        for acl in acls:
                            p_type = acl.principal_type.value if hasattr(acl.principal_type, "value") else str(acl.principal_type)
                            cur.execute("""
                                INSERT INTO acl_references (resource_type, resource_id, principal_type, principal_id, permission)
                                VALUES (%s, %s, %s, %s, %s);
                            """, (acl.resource_type, acl.resource_id, p_type, acl.principal_id, acl.permission))

                        # 7. Entities validation & insert/upsert
                        self._save_entities_with_cursor(cur, entities)

                        # 8. Scoped relationship ownership replacement and immutable upsert
                        if item_ids:
                            cur.execute("""
                                SELECT DISTINCT relationship_id FROM relationship_owners WHERE source_record_id = ANY(%s);
                            """, (item_ids,))
                            affected_rel_ids = [r[0] for r in cur.fetchall()]
                            cur.execute("""
                                DELETE FROM relationship_owners WHERE source_record_id = ANY(%s);
                            """, (item_ids,))
                            if affected_rel_ids:
                                cur.execute("""
                                    DELETE FROM relationships 
                                    WHERE id = ANY(%s) 
                                      AND NOT EXISTS (SELECT 1 FROM relationship_owners ro WHERE ro.relationship_id = relationships.id);
                                """, (affected_rel_ids,))

                        for rel in relationships:
                            canonical_meta = derive_canonical_metadata(rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
                            # Verify incoming rel.metadata vs canonical
                            for k, v in canonical_meta.items():
                                if k in rel.metadata and str(rel.metadata[k]) != str(v):
                                    raise ValueError(
                                        f"Metadata conflict for relationship ({rel.source_entity_id}, {rel.target_entity_id}, {rel.relationship_type}): "
                                        f"key '{k}' has conflicting values '{rel.metadata[k]}' vs '{v}'"
                                    )

                            cur.execute("""
                                INSERT INTO relationships (source_entity_id, target_entity_id, relationship_type, metadata, created_at)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (source_entity_id, target_entity_id, relationship_type) 
                                DO NOTHING
                                RETURNING id;
                            """, (
                                rel.source_entity_id,
                                rel.target_entity_id,
                                rel.relationship_type,
                                json.dumps(canonical_meta),
                                rel.created_at,
                            ))
                            row_insert = cur.fetchone()
                            if row_insert:
                                rel_id = row_insert[0]
                            else:
                                cur.execute("""
                                    SELECT id, metadata FROM relationships
                                    WHERE source_entity_id = %s AND target_entity_id = %s AND relationship_type = %s;
                                """, (rel.source_entity_id, rel.target_entity_id, rel.relationship_type))
                                existing_row = cur.fetchone()
                                if not existing_row:
                                    continue
                                rel_id = existing_row[0]
                                stored_meta = existing_row[1] if isinstance(existing_row[1], dict) else json.loads(existing_row[1] or "{}")
                                for k, v in canonical_meta.items():
                                    if k in stored_meta and str(stored_meta[k]) != str(v):
                                        raise ValueError(
                                            f"Stored relationship metadata conflict for ({rel.source_entity_id}, {rel.target_entity_id}, {rel.relationship_type}): "
                                            f"stored '{k}'='{stored_meta[k]}' != canonical '{v}'"
                                        )

                            owners = set()
                            if "source_record_id" in rel.metadata and rel.metadata["source_record_id"]:
                                owners.add(rel.metadata["source_record_id"])
                            if "source_record_ids" in rel.metadata and isinstance(rel.metadata["source_record_ids"], list):
                                owners.update(rel.metadata["source_record_ids"])
                            for owner_id in owners:
                                cur.execute("""
                                    INSERT INTO relationship_owners (relationship_id, source_record_id)
                                    VALUES (%s, %s)
                                    ON CONFLICT (relationship_id, source_record_id) DO NOTHING;
                                """, (rel_id, owner_id))

                        # 9. In the SAME transaction: advance checkpoint with status = 'SYNCING'
                        cur.execute("""
                            UPDATE sync_state
                            SET status = 'SYNCING',
                                cursor_value = %s,
                                records_synced_last_run = COALESCE(records_synced_last_run, 0) + %s,
                                updated_at = clock_timestamp()
                            WHERE source_type = %s 
                              AND metadata->>'lease_token' = %s;
                        """, (next_cursor, len(items), source_type, lease_token))
        except (DatabaseUnavailableError, FencedSyncError, ValueError):
            raise
        except Exception as e:
            logger.error("postgres_persist_sync_batch_failed source_type=%s err=%s", source_type, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def save_source_records(self, items: List[RawSourceItem]) -> None:
        if not items:
            return
        query = """
            INSERT INTO source_records (
                id, source_type, source_id, source_url, title, author_id,
                raw_content, metadata, version, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                raw_content = EXCLUDED.raw_content,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at;
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                for item in items:
                    cur.execute(
                        query,
                        (
                            item.id,
                            item.source_type.value,
                            item.source_id,
                            item.source_url,
                            item.title,
                            item.author_id,
                            item.raw_content,
                            json.dumps(item.metadata),
                            item.version,
                            item.created_at,
                            item.updated_at,
                        ),
                    )
            conn.commit()

    def save_documents(self, docs: List[CanonicalDocument]) -> None:
        if not docs:
            return
        query = """
            INSERT INTO documents (
                id, source_record_id, source_type, title, content, author, url,
                metadata, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at;
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                for doc in docs:
                    cur.execute(
                        query,
                        (
                            doc.id,
                            doc.source_record_id,
                            doc.source_type,
                            doc.title,
                            doc.content,
                            doc.author,
                            doc.url,
                            json.dumps(doc.metadata),
                            doc.created_at,
                            doc.updated_at,
                        ),
                    )
            conn.commit()

    def save_chunks(self, chunks: List[CanonicalChunk]) -> None:
        if not chunks:
            return
        query = """
            INSERT INTO chunks (
                id, document_id, chunk_index, content, token_count,
                embedding, metadata, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                token_count = EXCLUDED.token_count,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata;
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                for chunk in chunks:
                    cur.execute(
                        query,
                        (
                            chunk.id,
                            chunk.document_id,
                            chunk.chunk_index,
                            chunk.content,
                            chunk.token_count,
                            chunk.embedding,
                            json.dumps(chunk.metadata),
                            chunk.created_at,
                        ),
                    )
            conn.commit()

    def save_acls(self, acls: List[AclReference]) -> None:
        if not acls:
            return
        query = """
            INSERT INTO acl_references (
                resource_type, resource_id, principal_type, principal_id, permission, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_type, resource_id, principal_type, principal_id, permission) DO NOTHING;
        """
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                for acl in acls:
                    cur.execute(
                        query,
                        (
                            acl.resource_type,
                            acl.resource_id,
                            acl.principal_type.value if hasattr(acl.principal_type, "value") else str(acl.principal_type),
                            acl.principal_id,
                            acl.permission,
                            acl.created_at,
                        ),
                    )
            conn.commit()

    def _prevalidate_entities(self, entities: List[Entity]) -> Dict[str, Optional[str]]:
        batch_anchors: Dict[str, Optional[str]] = {}
        for entity in entities:
            if entity.entity_type in {EntityType.TICKET.value, EntityType.EMPLOYEE.value}:
                entity.source_record_id = None
            elif entity.source_record_id is None:
                raise ValueError(
                    f"Anchored entity '{entity.id}' of type '{entity.entity_type}' requires a non-null source_record_id"
                )

            if entity.id in batch_anchors:
                if batch_anchors[entity.id] != entity.source_record_id:
                    raise ValueError(
                        f"Provenance conflict within batch for entity '{entity.id}': "
                        f"'{batch_anchors[entity.id]}' vs '{entity.source_record_id}'"
                    )
            else:
                batch_anchors[entity.id] = entity.source_record_id
        return batch_anchors

    def _save_entities_with_cursor(
        self, cur, entities: List[Entity], batch_anchors: Optional[Dict[str, Optional[str]]] = None
    ) -> None:
        if not entities:
            return

        if batch_anchors is None:
            batch_anchors = self._prevalidate_entities(entities)

        # 2. Pre-check existing persisted records in this transaction
        entity_ids = list(batch_anchors.keys())
        cur.execute(
            "SELECT id, source_record_id FROM entities WHERE id = ANY(%s);",
            (entity_ids,),
        )
        existing_rows = cur.fetchall()
        existing_map = {row[0]: row[1] for row in existing_rows}
        for entity in entities:
            if entity.id in existing_map:
                existing_src = existing_map[entity.id]
                if existing_src != entity.source_record_id:
                    raise ValueError(
                        f"Provenance conflict for entity '{entity.id}': "
                        f"existing source_record_id='{existing_src}', "
                        f"incoming source_record_id='{entity.source_record_id}'"
                    )

        # 3. Conflict-aware SQL execution
        upsert_query = """
            INSERT INTO entities (id, entity_type, name, source_record_id, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                metadata = EXCLUDED.metadata
            WHERE entities.source_record_id IS NOT DISTINCT FROM EXCLUDED.source_record_id
            RETURNING id;
        """
        for entity in entities:
            cur.execute(
                upsert_query,
                (
                    entity.id,
                    entity.entity_type,
                    entity.name,
                    entity.source_record_id,
                    json.dumps(entity.metadata),
                    entity.created_at,
                ),
            )
            row = cur.fetchone()
            if not row:
                cur.execute("SELECT source_record_id FROM entities WHERE id = %s;", (entity.id,))
                res = cur.fetchone()
                actual_src = res[0] if res else "unknown"
                raise ValueError(
                    f"Provenance conflict for entity '{entity.id}': "
                    f"existing source_record_id='{actual_src}', "
                    f"incoming source_record_id='{entity.source_record_id}'"
                )

    def save_entities(self, entities: List[Entity]) -> None:
        if not entities:
            return
        batch_anchors = self._prevalidate_entities(entities)
        try:
            with self._get_connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        self._save_entities_with_cursor(cur, entities, batch_anchors=batch_anchors)
        except DatabaseUnavailableError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error("postgres_save_entities_failed err=%s", e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def save_relationships(self, relationships: List[Relationship]) -> None:
        if not relationships:
            return
        try:
            with self._get_connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        for rel in relationships:
                            canonical_meta = derive_canonical_metadata(rel.source_entity_id, rel.target_entity_id, rel.relationship_type)
                            for k, v in canonical_meta.items():
                                if k in rel.metadata and str(rel.metadata[k]) != str(v):
                                    raise ValueError(
                                        f"Metadata conflict for relationship ({rel.source_entity_id}, {rel.target_entity_id}, {rel.relationship_type}): "
                                        f"incoming '{k}'='{rel.metadata[k]}' != canonical '{v}'"
                                    )

                            cur.execute("""
                                INSERT INTO relationships (source_entity_id, target_entity_id, relationship_type, metadata, created_at)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (source_entity_id, target_entity_id, relationship_type) DO NOTHING
                                RETURNING id;
                            """, (
                                rel.source_entity_id,
                                rel.target_entity_id,
                                rel.relationship_type,
                                json.dumps(canonical_meta),
                                rel.created_at,
                            ))
                            row_insert = cur.fetchone()
                            if row_insert:
                                rel_id = row_insert[0]
                            else:
                                cur.execute("""
                                    SELECT id, metadata FROM relationships
                                    WHERE source_entity_id = %s AND target_entity_id = %s AND relationship_type = %s;
                                """, (rel.source_entity_id, rel.target_entity_id, rel.relationship_type))
                                existing_row = cur.fetchone()
                                if not existing_row:
                                    continue
                                rel_id = existing_row[0]
                                stored_meta = existing_row[1] if isinstance(existing_row[1], dict) else json.loads(existing_row[1] or "{}")
                                for k, v in canonical_meta.items():
                                    if k in stored_meta and str(stored_meta[k]) != str(v):
                                        raise ValueError(
                                            f"Stored relationship metadata conflict for ({rel.source_entity_id}, {rel.target_entity_id}, {rel.relationship_type}): "
                                            f"stored '{k}'='{stored_meta[k]}' != canonical '{v}'"
                                        )

                            owners = set()
                            if "source_record_id" in rel.metadata and rel.metadata["source_record_id"]:
                                owners.add(rel.metadata["source_record_id"])
                            if "source_record_ids" in rel.metadata and isinstance(rel.metadata["source_record_ids"], list):
                                owners.update(rel.metadata["source_record_ids"])
                            # Documented extraction fallback if unassigned
                            if not owners:
                                if rel.relationship_type == RelationshipType.IMPLEMENTED_BY.value:
                                    cur.execute("SELECT source_record_id FROM entities WHERE id = %s;", (rel.target_entity_id,))
                                    r = cur.fetchone()
                                    if r and r[0]:
                                        owners.add(r[0])
                                elif rel.relationship_type == RelationshipType.DISCUSSED_IN.value:
                                    cur.execute("SELECT source_record_id FROM entities WHERE id = %s;", (rel.target_entity_id,))
                                    r = cur.fetchone()
                                    if r and r[0]:
                                        owners.add(r[0])
                                elif rel.relationship_type == RelationshipType.AUTHORED_BY.value:
                                    cur.execute("SELECT source_record_id FROM entities WHERE id = %s;", (rel.source_entity_id,))
                                    r = cur.fetchone()
                                    if r and r[0]:
                                        owners.add(r[0])
                                elif rel.relationship_type == RelationshipType.CONTAINS.value:
                                    cur.execute("SELECT source_record_id FROM entities WHERE id = %s;", (rel.source_entity_id,))
                                    r = cur.fetchone()
                                    if r and r[0]:
                                        owners.add(r[0])

                            for owner_id in owners:
                                cur.execute("""
                                    INSERT INTO relationship_owners (relationship_id, source_record_id)
                                    VALUES (%s, %s)
                                    ON CONFLICT (relationship_id, source_record_id) DO NOTHING;
                                """, (rel_id, owner_id))
        except DatabaseUnavailableError:
            raise
        except ValueError:
            raise
        except Exception as e:
            logger.error("postgres_save_relationships_failed err=%s", e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def get_entity(
        self,
        entity_id: str,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> Optional[Entity]:
        clean_user = str(user_id).strip() if user_id and str(user_id).strip() else None
        clean_groups = [str(g).strip() for g in group_ids if str(g).strip()] if group_ids else []

        principal_conditions = ["a.principal_type = 'PUBLIC'"]
        acl_params: List[Any] = []
        if clean_user:
            principal_conditions.append("(a.principal_type = 'USER' AND a.principal_id = %s)")
            acl_params.append(clean_user)
        if clean_groups:
            principal_conditions.append("(a.principal_type = 'GROUP' AND a.principal_id = ANY(%s))")
            acl_params.append(clean_groups)
        principals_sql = " OR ".join(principal_conditions)

        query = f"""
            SELECT e.id, e.entity_type, e.name, e.source_record_id, e.metadata, e.created_at,
                   -- Branch 1: Direct primary anchor authorization
                   (e.source_record_id IS NOT NULL AND EXISTS (
                       SELECT 1 FROM acl_references a
                       WHERE a.resource_type = 'SOURCE_RECORD'
                         AND a.resource_id = e.source_record_id
                         AND UPPER(a.permission) = 'READ'
                         AND ({principals_sql})
                   )) AS is_direct_anchor_authorized,
                   -- Branch 2: Supporting relationship provenance authorization
                   EXISTS (
                       SELECT 1 
                       FROM relationships r
                       JOIN relationship_owners ro ON ro.relationship_id = r.id
                       JOIN acl_references a ON (
                           a.resource_type = 'SOURCE_RECORD'
                           AND a.resource_id = ro.source_record_id
                           AND UPPER(a.permission) = 'READ'
                           AND ({principals_sql})
                       )
                       WHERE r.source_entity_id = e.id OR r.target_entity_id = e.id
                   ) AS is_rel_provenance_authorized
            FROM entities e
            WHERE e.id = %s;
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, tuple(acl_params + acl_params + [entity_id]))
                    row = cur.fetchone()
                    if not row:
                        return None

                    eid, etype, name, s_rec_id, meta, created_at, is_direct_auth, is_rel_auth = row
                    if not (is_direct_auth or is_rel_auth):
                        return None

                    meta_dict = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                    safe_source_record_id = s_rec_id if is_direct_auth else None
                    safe_metadata = meta_dict if is_direct_auth else {
                        k: v for k, v in meta_dict.items()
                        if k in {"repository", "number", "sha", "channel_id", "thread_ts", "ticket_id"}
                    }

                    return Entity(
                        id=eid,
                        entity_type=etype,
                        name=name,
                        source_record_id=safe_source_record_id,
                        metadata=safe_metadata,
                        created_at=created_at,
                    )
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_get_entity_failed entity_id=%s err=%s", entity_id, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def get_relationships_for_entity(
        self,
        entity_id: str,
        relationship_type: Optional[str] = None,
        direction: str = "OUTGOING",
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[Tuple[Relationship, Entity]]:
        norm_dir = direction.upper().strip()
        if norm_dir not in {"OUTGOING", "INCOMING", "BOTH"}:
            raise ValueError(f"Invalid traversal direction '{direction}': must be OUTGOING, INCOMING, or BOTH")

        start_entity = self.get_entity(entity_id, user_id=user_id, group_ids=group_ids)
        if not start_entity:
            return []

        clean_user = str(user_id).strip() if user_id and str(user_id).strip() else None
        clean_groups = [str(g).strip() for g in group_ids if str(g).strip()] if group_ids else []

        principal_conditions = ["a.principal_type = 'PUBLIC'"]
        acl_params: List[Any] = []
        if clean_user:
            principal_conditions.append("(a.principal_type = 'USER' AND a.principal_id = %s)")
            acl_params.append(clean_user)
        if clean_groups:
            principal_conditions.append("(a.principal_type = 'GROUP' AND a.principal_id = ANY(%s))")
            acl_params.append(clean_groups)
        principals_sql = " OR ".join(principal_conditions)

        where_parts = []
        query_params: List[Any] = []

        if norm_dir == "OUTGOING":
            where_parts.append("r.source_entity_id = %s")
            query_params.append(entity_id)
        elif norm_dir == "INCOMING":
            where_parts.append("r.target_entity_id = %s")
            query_params.append(entity_id)
        elif norm_dir == "BOTH":
            where_parts.append("(r.source_entity_id = %s OR r.target_entity_id = %s)")
            query_params.extend([entity_id, entity_id])

        if relationship_type:
            where_parts.append("r.relationship_type = %s")
            query_params.append(relationship_type)

        na_principals_sql = principals_sql.replace("a.", "na.")

        query = f"""
            SELECT r.source_entity_id, r.target_entity_id, r.relationship_type, r.metadata, r.created_at,
                   n.id, n.entity_type, n.name, n.source_record_id, n.metadata, n.created_at,
                   (n.source_record_id IS NOT NULL AND EXISTS (
                       SELECT 1 FROM acl_references na
                       WHERE na.resource_type = 'SOURCE_RECORD'
                         AND na.resource_id = n.source_record_id
                         AND UPPER(na.permission) = 'READ'
                         AND ({na_principals_sql})
                   )) AS is_direct_neighbor_auth
            FROM relationships r
            JOIN entities n ON (
                CASE
                    WHEN %s = 'OUTGOING' THEN r.target_entity_id = n.id
                    WHEN %s = 'INCOMING' THEN r.source_entity_id = n.id
                    ELSE (r.source_entity_id = %s AND r.target_entity_id = n.id)
                      OR (r.target_entity_id = %s AND r.source_entity_id = n.id)
                END
            )
            WHERE {" AND ".join(where_parts)}
              AND EXISTS (
                  SELECT 1 
                  FROM relationship_owners ro
                  JOIN acl_references a ON (
                      a.resource_type = 'SOURCE_RECORD'
                      AND a.resource_id = ro.source_record_id
                      AND UPPER(a.permission) = 'READ'
                      AND ({principals_sql})
                  )
                  WHERE ro.relationship_id = r.id
              )
            ORDER BY r.relationship_type, r.id;
        """
        all_params = (
            acl_params
            + [norm_dir, norm_dir, entity_id, entity_id]
            + query_params
            + acl_params
        )
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, tuple(all_params))
                    rows = cur.fetchall()

            results: List[Tuple[Relationship, Entity]] = []
            for row in rows:
                (
                    s_id, t_id, r_type, r_meta, r_created,
                    n_id, n_type, n_name, n_s_rec_id, n_meta, n_created,
                    is_direct_neighbor_auth,
                ) = row
                rel_meta_dict = r_meta if isinstance(r_meta, dict) else json.loads(r_meta or "{}")
                n_meta_dict = n_meta if isinstance(n_meta, dict) else json.loads(n_meta or "{}")

                rel = Relationship(
                    source_entity_id=s_id,
                    target_entity_id=t_id,
                    relationship_type=r_type,
                    metadata=rel_meta_dict,
                    created_at=r_created,
                )

                if is_direct_neighbor_auth:
                    neighbor_entity = Entity(
                        id=n_id,
                        entity_type=n_type,
                        name=n_name,
                        source_record_id=n_s_rec_id,
                        metadata=n_meta_dict,
                        created_at=n_created,
                    )
                else:
                    canonical_rel_meta = derive_canonical_metadata(s_id, t_id, r_type)
                    safe_neighbor_meta = {
                        k: v for k, v in n_meta_dict.items()
                        if k in {"repository", "number", "sha", "channel_id", "thread_ts", "ticket_id"} and (k in canonical_rel_meta or k == "number")
                    }
                    neighbor_entity = Entity(
                        id=n_id,
                        entity_type=n_type,
                        name=n_name,
                        source_record_id=None,
                        metadata=safe_neighbor_meta,
                        created_at=n_created,
                    )

                results.append((rel, neighbor_entity))

            results.sort(key=lambda x: (x[0].relationship_type, x[1].id))
            return results
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_get_relationships_for_entity_failed entity_id=%s err=%s", entity_id, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def search_lexical(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        if not query or not query.strip():
            return []

        cleaned_query = query.strip()
        acl_clause, acl_params = build_acl_where_clause(
            user_id=user_id,
            group_ids=group_ids,
            doc_alias="d",
            chunk_alias="c",
            acl_alias="a",
        )
        where_clauses = [
            "c.tsv @@ plainto_tsquery('english', %s)",
            acl_clause,
        ]
        params: List[Any] = [cleaned_query, cleaned_query]
        params.extend(acl_params)
        if source_types:
            where_clauses.append("d.source_type = ANY(%s)")
            params.append(source_types)
        params.append(limit)

        sql = f"""
            SELECT
                c.id,
                c.document_id,
                d.source_type,
                COALESCE(d.title, ''),
                c.content,
                COALESCE(d.url, ''),
                d.author,
                ts_rank_cd(c.tsv, plainto_tsquery('english', %s)) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE {" AND ".join(where_clauses)}
            ORDER BY score DESC, c.created_at DESC
            LIMIT %s;
        """
        results: List[RagSearchResultItem] = []
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, tuple(params))
                    rows = cur.fetchall()
                    for row in rows:
                        chunk_id, doc_id, src_type, title, content, url, author, score = row
                        snippet = content[:300].strip() + ("..." if len(content) > 300 else "")
                        results.append(
                            RagSearchResultItem(
                                chunk_id=chunk_id,
                                document_id=doc_id,
                                source_type=src_type,
                                title=title,
                                snippet=snippet,
                                source_url=url,
                                author=author,
                                score=round(float(score), 4) if score is not None else 0.0,
                            )
                        )
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_search_lexical_failed query=%s err=%s", cleaned_query, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

        return results

    def search_vector(
        self,
        query_embedding: List[float],
        limit: int = 10,
        source_types: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        expected_dim = get_settings().embedding_dimension
        if len(query_embedding) != expected_dim:
            raise ValueError(
                f"Query embedding dimension mismatch: expected {expected_dim}, got {len(query_embedding)}"
            )

        q_norm = math.sqrt(sum(x * x for x in query_embedding))
        if q_norm == 0.0 or math.isclose(q_norm, 0.0, abs_tol=1e-12):
            return []

        acl_clause, acl_params = build_acl_where_clause(
            user_id=user_id,
            group_ids=group_ids,
            doc_alias="d",
            chunk_alias="c",
            acl_alias="a",
        )
        vec_param: Any = query_embedding
        try:
            from pgvector import Vector
            vec_param = Vector(query_embedding)
        except Exception:
            pass

        # PostgreSQL cannot push down correlated multi-table ACL subqueries with OR joins
        # into pgvector HNSW index scans, forcing a 4-6s seq scan + 52M-row nested loop.
        # We configure HNSW ef_search and retrieve top candidate nearest neighbors directly via HNSW (candidate_k),
        # then apply the ACL and source filtering on candidates (~15-30ms latency).
        candidate_k = max(100, limit * 10)

        outer_where = [acl_clause]
        outer_params: List[Any] = list(acl_params)
        if source_types:
            outer_where.append("d.source_type = ANY(%s)")
            outer_params.append(source_types)

        sql_fast = f"""
            WITH candidates AS (
                SELECT
                    c.id,
                    c.document_id,
                    c.content,
                    (c.embedding <=> %s) AS dist
                FROM chunks c
                WHERE c.embedding IS NOT NULL AND (- (c.embedding <#> c.embedding)) > 0
                ORDER BY c.embedding <=> %s ASC
                LIMIT %s
            )
            SELECT
                c.id,
                c.document_id,
                d.source_type,
                COALESCE(d.title, ''),
                c.content,
                COALESCE(d.url, ''),
                d.author,
                ROUND((1 - c.dist)::numeric, 4) AS score
            FROM candidates c
            JOIN documents d ON c.document_id = d.id
            WHERE {" AND ".join(outer_where)}
            ORDER BY c.dist ASC
            LIMIT %s;
        """
        fast_params = [vec_param, vec_param, candidate_k] + outer_params + [limit]

        sql_fallback = f"""
            SELECT
                c.id,
                c.document_id,
                d.source_type,
                COALESCE(d.title, ''),
                c.content,
                COALESCE(d.url, ''),
                d.author,
                ROUND((1 - (c.embedding <=> %s))::numeric, 4) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.embedding IS NOT NULL AND (- (c.embedding <#> c.embedding)) > 0
              AND {" AND ".join(outer_where)}
            ORDER BY c.embedding <=> %s ASC
            LIMIT %s;
        """
        fallback_params = [vec_param] + outer_params + [vec_param, limit]

        results: List[RagSearchResultItem] = []
        try:
            with self._get_connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("SET LOCAL hnsw.ef_search = 100;")
                        try:
                            cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
                        except Exception:
                            pass
                        cur.execute(sql_fast, tuple(fast_params))
                        rows = cur.fetchall()
                        if len(rows) < limit:
                            # Low-access user or sparse candidate survival; execute exact fallback with iterative scan
                            cur.execute(sql_fallback, tuple(fallback_params))
                            rows = cur.fetchall()
                        for row in rows:
                            chunk_id, doc_id, src_type, title, content, url, author, score = row
                            snippet = content[:300].strip() + ("..." if len(content) > 300 else "")
                            results.append(
                                RagSearchResultItem(
                                    chunk_id=chunk_id,
                                    document_id=doc_id,
                                    source_type=src_type,
                                    title=title,
                                    snippet=snippet,
                                    source_url=url,
                                    author=author,
                                    score=round(float(score), 4) if score is not None else 0.0,
                                )
                            )
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_search_vector_failed err=%s", e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e
        return results

    def record_audit_event(
        self,
        user_id: str,
        action: str,
        resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        query = """
            INSERT INTO audit_events (user_id, action, resource, details, ip_address, timestamp)
            VALUES (%s, %s, %s, %s, %s, clock_timestamp());
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (
                            user_id,
                            action,
                            resource,
                            json.dumps(details or {}),
                            ip_address,
                        ),
                    )
                conn.commit()
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_record_audit_event_failed user_id=%s action=%s err=%s", user_id, action, e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def _build_audit_where(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> tuple[str, List[Any]]:
        where_clauses = []
        params: List[Any] = []
        if user_id:
            where_clauses.append("user_id = %s")
            params.append(user_id)
        if action:
            where_clauses.append("action = %s")
            params.append(action)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        return where_sql, params

    def get_audit_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        where_sql, params = self._build_audit_where(user_id=user_id, action=action)
        query = f"""
            SELECT id, user_id, action, resource, details, ip_address, timestamp
            FROM audit_events
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT %s OFFSET %s;
        """
        params.extend([limit, offset])
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()
            events = []
            for r in rows:
                meta = r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}")
                events.append({
                    "id": r[0],
                    "userId": r[1],
                    "action": r[2],
                    "resource": r[3],
                    "details": meta,
                    "ipAddress": r[5],
                    "timestamp": r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
                })
            return events
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_get_audit_events_failed err=%s", e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

    def count_audit_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> int:
        where_sql, params = self._build_audit_where(user_id=user_id, action=action)
        query = f"SELECT COUNT(*) FROM audit_events {where_sql};"
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, tuple(params))
                    row = cur.fetchone()
                    return int(row[0]) if row else 0
        except DatabaseUnavailableError:
            raise
        except Exception as e:
            logger.error("postgres_count_audit_events_failed err=%s", e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

