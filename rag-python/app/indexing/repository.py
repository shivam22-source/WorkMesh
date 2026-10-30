"""Repository layer for persisting canonical knowledge, vectors, ACLs, and sync state."""

from abc import ABC, abstractmethod
import json
import logging
from typing import Dict, List, Optional

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, RawSourceItem
from app.indexing.models import SyncStateRecord
from app.normalization.models import CanonicalDocument

logger = logging.getLogger(__name__)


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


class InMemoryKnowledgeRepository(KnowledgeRepository):
    """In-memory repository used for fast, isolated unit and pipeline testing."""

    def __init__(self):
        self.sync_states: Dict[str, SyncStateRecord] = {}
        self.source_records: Dict[str, RawSourceItem] = {}
        self.documents: Dict[str, CanonicalDocument] = {}
        self.chunks: Dict[str, CanonicalChunk] = {}
        self.acls: List[AclReference] = []

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


class PostgresKnowledgeRepository(KnowledgeRepository):
    """PostgreSQL + pgvector implementation using psycopg."""

    def __init__(self, connection_url: str):
        self.connection_url = connection_url

    def _get_connection(self):
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(self.connection_url)
        register_vector(conn)
        return conn

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
