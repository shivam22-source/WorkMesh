"""Repository layer for persisting canonical knowledge, vectors, ACLs, and sync state."""

from abc import ABC, abstractmethod
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import AclReference, RawSourceItem
from app.contracts.rag_search import RagSearchResultItem
from app.indexing.models import SyncStateRecord
from app.normalization.models import CanonicalDocument

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
    def search_lexical(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Perform lexical (full-text) search over indexed chunks."""
        ...

    @abstractmethod
    def search_vector(
        self,
        query_embedding: List[float],
        limit: int = 10,
        source_types: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        """Perform vector similarity search over indexed chunks."""
        ...


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

    def search_lexical(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
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

    def search_lexical(
        self,
        query: str,
        limit: int = 10,
        source_types: Optional[List[str]] = None,
    ) -> List[RagSearchResultItem]:
        if not query or not query.strip():
            return []

        cleaned_query = query.strip()
        where_clauses = ["c.tsv @@ plainto_tsquery('english', %s)"]
        params = [cleaned_query, cleaned_query]
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
    ) -> List[RagSearchResultItem]:
        expected_dim = 1536
        if len(query_embedding) != expected_dim:
            raise ValueError(
                f"Query embedding dimension mismatch: expected {expected_dim}, got {len(query_embedding)}"
            )

        q_norm = math.sqrt(sum(x * x for x in query_embedding))
        if q_norm == 0.0 or math.isclose(q_norm, 0.0, abs_tol=1e-12):
            return []

        where_clauses = [
            "c.embedding IS NOT NULL",
            "(- (c.embedding <#> c.embedding)) > 0",  # Exclude zero chunk vectors
        ]
        params: List[Any] = [query_embedding]

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
