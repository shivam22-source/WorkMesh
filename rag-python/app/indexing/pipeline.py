"""Ingestion pipeline orchestrating connector -> normalize -> chunk -> embed -> index -> checkpoint."""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Union

from app.chunking.models import CanonicalChunk
from app.chunking.source_aware_chunker import SourceAwareChunker
from app.connectors.common.base import SourceConnector
from app.connectors.common.models import AclReference, RawSourceItem, SourceType
from app.embeddings.base import EmbeddingProvider
from app.indexing.models import SyncResult, SyncStateRecord
from app.indexing.repository import KnowledgeRepository
from app.normalization.github_normalizer import GitHubNormalizer
from app.normalization.models import CanonicalDocument
from app.normalization.slack_normalizer import SlackNormalizer

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """End-to-end ingestion orchestrator for external and fixture sources."""

    def __init__(
        self,
        connector: SourceConnector,
        repository: KnowledgeRepository,
        embedding_provider: EmbeddingProvider,
        chunker: Optional[SourceAwareChunker] = None,
        normalizer: Optional[Union[GitHubNormalizer, SlackNormalizer]] = None,
    ):
        self.connector = connector
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.chunker = chunker or SourceAwareChunker()
        if normalizer is not None:
            self.normalizer = normalizer
        elif self.connector.source_type == SourceType.SLACK:
            self.normalizer = SlackNormalizer()
        else:
            self.normalizer = GitHubNormalizer()

    def run(self) -> SyncResult:
        started_at = datetime.now(timezone.utc)
        source_type_str = self.connector.source_type.value
        logger.info("ingestion_pipeline_started source=%s", source_type_str)

        # 1. Retrieve current sync checkpoint
        sync_state = self.repository.get_sync_state(source_type_str)
        if not sync_state:
            sync_state = SyncStateRecord(
                source_type=source_type_str,
                cursor_value=None,
                status="IDLE",
            )

        last_cursor = sync_state.cursor_value
        sync_state.status = "SYNCING"
        sync_state.last_sync_started_at = started_at
        self.repository.update_sync_state(sync_state)

        try:
            # 2. Extract changed items from connector
            raw_items, next_cursor = self.connector.list_changes(cursor=last_cursor)
            if not raw_items:
                logger.info("no_new_items_found source=%s cursor=%s", source_type_str, last_cursor)
                sync_state.status = "SUCCESS"
                sync_state.last_sync_completed_at = datetime.now(timezone.utc)
                sync_state.records_synced_last_run = 0
                sync_state.error_message = None
                self.repository.update_sync_state(sync_state)
                return SyncResult(
                    source_type=source_type_str,
                    status="SUCCESS",
                    records_ingested=0,
                    chunks_indexed=0,
                    new_cursor=last_cursor,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                )

            logger.info("extracted_raw_items count=%d source=%s", len(raw_items), source_type_str)

            # 3. Normalize into canonical documents & extract ACLs
            docs: List[CanonicalDocument] = []
            all_acls: List[AclReference] = []

            for item in raw_items:
                item_acls = self.connector.extract_acl(item)
                all_acls.extend(item_acls)
                doc = self.normalizer.normalize(item, item_acls)
                docs.append(doc)

            # 4. Source-aware chunking
            all_chunks: List[CanonicalChunk] = []
            for doc in docs:
                chunks = self.chunker.chunk(doc)
                all_chunks.extend(chunks)

            logger.info("chunked_documents docs=%d chunks=%d", len(docs), len(all_chunks))

            # 5. Generate vector embeddings for all chunks
            if all_chunks:
                texts = [c.content for c in all_chunks]
                embeddings = self.embedding_provider.embed_texts(texts)
                for chunk, emb in zip(all_chunks, embeddings):
                    chunk.embedding = emb

            # 6. Persist to repository
            self.repository.save_source_records(raw_items)
            self.repository.save_documents(docs)
            self.repository.save_chunks(all_chunks)
            self.repository.save_acls(all_acls)

            # 7. Checkpoint cursor update
            completed_at = datetime.now(timezone.utc)
            sync_state.status = "SUCCESS"
            sync_state.cursor_value = next_cursor
            sync_state.last_sync_completed_at = completed_at
            sync_state.records_synced_last_run = len(raw_items)
            sync_state.error_message = None
            self.repository.update_sync_state(sync_state)

            logger.info(
                "ingestion_pipeline_succeeded source=%s records=%d chunks=%d new_cursor=%s",
                source_type_str,
                len(raw_items),
                len(all_chunks),
                next_cursor,
            )

            return SyncResult(
                source_type=source_type_str,
                status="SUCCESS",
                records_ingested=len(raw_items),
                chunks_indexed=len(all_chunks),
                new_cursor=next_cursor,
                started_at=started_at,
                completed_at=completed_at,
            )

        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.exception("ingestion_pipeline_failed source=%s err=%s", source_type_str, error_msg)

            # Record failure in checkpoint without advancing the cursor so retry is possible
            sync_state.status = "FAILED"
            sync_state.error_message = error_msg
            sync_state.last_sync_completed_at = completed_at
            self.repository.update_sync_state(sync_state)

            return SyncResult(
                source_type=source_type_str,
                status="FAILED",
                records_ingested=0,
                chunks_indexed=0,
                new_cursor=last_cursor,
                error_message=error_msg,
                started_at=started_at,
                completed_at=completed_at,
            )
