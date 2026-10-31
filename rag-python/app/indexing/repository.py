"""Repository layer for persisting canonical knowledge, vectors, ACLs, and sync state."""

from abc import ABC, abstractmethod
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, RawSourceItem
from app.contracts.rag_search import RagSearchResultItem
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.models import SyncStateRecord
from app.normalization.models import CanonicalDocument
from app.security.acl import build_acl_where_clause, has_read_permission

logger = logging.getLogger(__name__)


class DatabaseUnavailableError(Exception):
    """Raised when PostgreSQL / pgvector service is unreachable or connection fails."""


class KnowledgeRepository(ABC):
    """Abstract persistence layer for knowledge records and vector chunks."""

    @abstractmethod
    def get_sync_state(self, source_type: str) -> Optional[SyncStateRecord]: ...

    @abstractmethod
    def update_sync_state(self, state: SyncStateRecord) -> None: ...

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


class InMemoryKnowledgeRepository(KnowledgeRepository):
    """In-memory repository used for fast, isolated unit and pipeline testing."""

    def __init__(self):
        self.sync_states: Dict[str, SyncStateRecord] = {}
        self.source_records: Dict[str, RawSourceItem] = {}
        self.documents: Dict[str, CanonicalDocument] = {}
        self.chunks: Dict[str, CanonicalChunk] = {}
        self.acls: List[AclReference] = []
        self.entities: Dict[str, Entity] = {}
        self.relationships: Dict[Tuple[str, str, str], Relationship] = {}

    def get_sync_state(self, source_type: str) -> Optional[SyncStateRecord]:
        return self.sync_states.get(source_type)

    def update_sync_state(self, state: SyncStateRecord) -> None:
        self.sync_states[state.source_type] = state

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
            if key in self.relationships:
                existing = self.relationships[key]
                existing.metadata = {**existing.metadata, **rel.metadata}
            else:
                self.relationships[key] = rel

    def get_entity(
        self,
        entity_id: str,
        user_id: Optional[str] = None,
        group_ids: Optional[List[str]] = None,
    ) -> Optional[Entity]:
        entity = self.entities.get(entity_id)
        if not entity:
            return None

        # 1. Anchored entity (PULL_REQUEST, COMMIT, SLACK_THREAD)
        if entity.source_record_id is not None:
            acls = [
                acl for acl in self.acls
                if acl.resource_type == "SOURCE_RECORD" and acl.resource_id == entity.source_record_id
            ]
            if not has_read_permission(acls, user_id=user_id, group_ids=group_ids):
                return None
            return entity

        # 2. Unanchored entity (TICKET, EMPLOYEE)
        # Provenance visibility rule: visible iff at least one incident relationship
        # connects to an authorized anchored entity.
        for rel in self.relationships.values():
            other_id = None
            if rel.source_entity_id == entity.id:
                other_id = rel.target_entity_id
            elif rel.target_entity_id == entity.id:
                other_id = rel.source_entity_id

            if other_id:
                other = self.entities.get(other_id)
                if other and other.source_record_id is not None:
                    other_acls = [
                        acl for acl in self.acls
                        if acl.resource_type == "SOURCE_RECORD" and acl.resource_id == other.source_record_id
                    ]
                    if has_read_permission(other_acls, user_id=user_id, group_ids=group_ids):
                        return entity

        # Deny by default: no authorized provenance exists
        return None

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

        # Starting entity must be authorized
        start_entity = self.get_entity(entity_id, user_id=user_id, group_ids=group_ids)
        if not start_entity:
            return []

        results: List[Tuple[Relationship, Entity]] = []

        for rel in self.relationships.values():
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

            # Neighbor entity must be authorized
            neighbor_entity = self.get_entity(neighbor_id, user_id=user_id, group_ids=group_ids)
            if not neighbor_entity:
                continue

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
        expected_dim = 1536
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

    def get_sync_state(self, source_type: str) -> Optional[SyncStateRecord]:
        query = """
            SELECT source_type, cursor_value, status, last_sync_started_at,
                   last_sync_completed_at, records_synced_last_run, error_message
            FROM sync_state WHERE source_type = %s;
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (source_type,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    return SyncStateRecord(
                        source_type=row[0],
                        cursor_value=row[1],
                        status=row[2],
                        last_sync_started_at=row[3],
                        last_sync_completed_at=row[4],
                        records_synced_last_run=row[5],
                        error_message=row[6],
                    )
        except Exception as e:
            logger.error("get_sync_state_failed source_type=%s err=%s", source_type, e)
            return None

    def update_sync_state(self, state: SyncStateRecord) -> None:
        query = """
            INSERT INTO sync_state (
                source_type, cursor_value, status, last_sync_started_at,
                last_sync_completed_at, records_synced_last_run, error_message, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (source_type) DO UPDATE SET
                cursor_value = EXCLUDED.cursor_value,
                status = EXCLUDED.status,
                last_sync_started_at = EXCLUDED.last_sync_started_at,
                last_sync_completed_at = EXCLUDED.last_sync_completed_at,
                records_synced_last_run = EXCLUDED.records_synced_last_run,
                error_message = EXCLUDED.error_message,
                updated_at = CURRENT_TIMESTAMP;
        """
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
                    ),
                )
            conn.commit()

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

    def save_entities(self, entities: List[Entity]) -> None:
        if not entities:
            return

        batch_anchors: Dict[str, Optional[str]] = {}

        # 1. Intra-batch pre-validation pass
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

        upsert_query = """
            INSERT INTO entities (id, entity_type, name, source_record_id, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                metadata = EXCLUDED.metadata
            WHERE entities.source_record_id IS NOT DISTINCT FROM EXCLUDED.source_record_id
            RETURNING id;
        """
        try:
            with self._get_connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
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
                                # WHERE condition failed on conflict due to concurrent/unseen provenance divergence
                                cur.execute("SELECT source_record_id FROM entities WHERE id = %s;", (entity.id,))
                                res = cur.fetchone()
                                actual_src = res[0] if res else "unknown"
                                raise ValueError(
                                    f"Provenance conflict for entity '{entity.id}': "
                                    f"existing source_record_id='{actual_src}', "
                                    f"incoming source_record_id='{entity.source_record_id}'"
                                )
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
        query = """
            INSERT INTO relationships (source_entity_id, target_entity_id, relationship_type, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_entity_id, target_entity_id, relationship_type) DO UPDATE SET
                metadata = EXCLUDED.metadata;
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    for rel in relationships:
                        cur.execute(
                            query,
                            (
                                rel.source_entity_id,
                                rel.target_entity_id,
                                rel.relationship_type,
                                json.dumps(rel.metadata),
                                rel.created_at,
                            ),
                        )
                conn.commit()
        except DatabaseUnavailableError:
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
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, entity_type, name, source_record_id, metadata, created_at FROM entities WHERE id = %s;",
                        (entity_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None

                    eid, etype, name, s_rec_id, meta, created_at = row
                    meta_dict = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                    entity = Entity(
                        id=eid,
                        entity_type=etype,
                        name=name,
                        source_record_id=s_rec_id,
                        metadata=meta_dict,
                        created_at=created_at,
                    )

                    clean_user = str(user_id).strip() if user_id is not None and str(user_id).strip() else None
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

                    # 1. Anchored entity: verify its source_record_id ACL
                    if entity.source_record_id is not None:
                        check_query = f"""
                            SELECT 1 FROM acl_references a
                            WHERE UPPER(a.permission) = 'READ'
                              AND a.resource_type = 'SOURCE_RECORD'
                              AND a.resource_id = %s
                              AND ({principals_sql})
                            LIMIT 1;
                        """
                        cur.execute(check_query, tuple([entity.source_record_id] + acl_params))
                        if cur.fetchone():
                            return entity
                        return None

                    # 2. Unanchored entity (TICKET, EMPLOYEE): verify incident relationship to authorized source record
                    incident_query = f"""
                        SELECT 1
                        FROM relationships r
                        JOIN entities other ON (
                            (r.source_entity_id = %s AND r.target_entity_id = other.id)
                            OR (r.target_entity_id = %s AND r.source_entity_id = other.id)
                        )
                        JOIN acl_references a ON (
                            a.resource_type = 'SOURCE_RECORD'
                            AND a.resource_id = other.source_record_id
                            AND UPPER(a.permission) = 'READ'
                        )
                        WHERE other.source_record_id IS NOT NULL
                          AND ({principals_sql})
                        LIMIT 1;
                    """
                    cur.execute(incident_query, tuple([entity_id, entity_id] + acl_params))
                    if cur.fetchone():
                        return entity
                    return None
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

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    where_parts = []
                    params: List[Any] = []

                    if norm_dir == "OUTGOING":
                        where_parts.append("r.source_entity_id = %s")
                        params.append(entity_id)
                    elif norm_dir == "INCOMING":
                        where_parts.append("r.target_entity_id = %s")
                        params.append(entity_id)
                    elif norm_dir == "BOTH":
                        where_parts.append("(r.source_entity_id = %s OR r.target_entity_id = %s)")
                        params.extend([entity_id, entity_id])

                    if relationship_type:
                        where_parts.append("r.relationship_type = %s")
                        params.append(relationship_type)

                    query = f"""
                        SELECT r.source_entity_id, r.target_entity_id, r.relationship_type, r.metadata, r.created_at
                        FROM relationships r
                        WHERE {" AND ".join(where_parts)}
                        ORDER BY r.relationship_type, r.id;
                    """
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()

            results: List[Tuple[Relationship, Entity]] = []
            for row in rows:
                s_id, t_id, r_type, meta, created_at = row
                meta_dict = meta if isinstance(meta, dict) else json.loads(meta or "{}")
                rel = Relationship(
                    source_entity_id=s_id,
                    target_entity_id=t_id,
                    relationship_type=r_type,
                    metadata=meta_dict,
                    created_at=created_at,
                )
                neighbor_id = t_id if s_id == entity_id else s_id
                neighbor_entity = self.get_entity(neighbor_id, user_id=user_id, group_ids=group_ids)
                if neighbor_entity:
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
        expected_dim = 1536
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
        where_clauses = [
            "c.embedding IS NOT NULL",
            "(- (c.embedding <#> c.embedding)) > 0",  # Exclude zero chunk vectors
            acl_clause,
        ]
        params: List[Any] = [query_embedding]
        params.extend(acl_params)

        if source_types:
            where_clauses.append("d.source_type = ANY(%s)")
            params.append(source_types)

        params.append(query_embedding)
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
                ROUND((1 - (c.embedding <=> %s))::numeric, 4) AS score
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE {" AND ".join(where_clauses)}
            ORDER BY c.embedding <=> %s ASC
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
            logger.error("postgres_search_vector_failed err=%s", e)
            raise DatabaseUnavailableError(f"Database query failed: {e}") from e

        return results
