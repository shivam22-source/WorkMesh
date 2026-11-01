"""Ingestion pipeline orchestrating connector -> normalize -> chunk -> embed -> index -> checkpoint."""

from datetime import datetime, timezone
import logging
from typing import List, Optional, Union
import uuid

from app.chunking.models import CanonicalChunk
from app.chunking.source_aware_chunker import SourceAwareChunker
from app.connectors.common.base import SourceConnector
from app.connectors.common.models import AclReference, RawSourceItem, SourceType
from app.embeddings.base import EmbeddingProvider
from app.graph.extractor import extract_entities_and_relationships
from app.indexing.models import SyncResult, SyncStateRecord
from app.indexing.repository import KnowledgeRepository
from app.indexing.retry import retry_with_backoff
from app.normalization.email_normalizer import EmailNormalizer
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
        normalizer: Optional[Union[GitHubNormalizer, SlackNormalizer, EmailNormalizer]] = None,
        batch_size: Optional[int] = None,
        lease_ttl_seconds: int = 300,
    ):
        self.connector = connector
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.chunker = chunker or SourceAwareChunker()
        self.batch_size = batch_size
        self.lease_ttl_seconds = lease_ttl_seconds
        if normalizer is not None:
            self.normalizer = normalizer
        elif self.connector.source_type == SourceType.SLACK:
            self.normalizer = SlackNormalizer()
        elif self.connector.source_type == SourceType.EMAIL:
            self.normalizer = EmailNormalizer()
        else:
            self.normalizer = GitHubNormalizer()

    def run(self) -> SyncResult:
        started_at = datetime.now(timezone.utc)
        source_type_str = self.connector.source_type.value
        logger.info("ingestion_pipeline_started source=%s", source_type_str)

        # 1. Claim atomic sync lease
        lease_token = uuid.uuid4().hex
        claim = self.repository.claim_sync(
            source_type=source_type_str,
            lease_token=lease_token,
            lease_ttl_seconds=self.lease_ttl_seconds,
        )
        if not claim:
            err = f"Could not acquire sync lease for source '{source_type_str}' (active or unexpired run)"
            logger.warning("ingestion_pipeline_claim_failed source=%s err=%s", source_type_str, err)
            return SyncResult(
                source_type=source_type_str,
                status="FAILED",
                records_ingested=0,
                chunks_indexed=0,
                new_cursor=None,
                error_message=err,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
            )

        current_cursor = claim.cursor_value
        total_records = 0
        total_chunks = 0
        last_committed_cursor = current_cursor

        try:
            while True:
                # 2. Renew lease before processing batch
                self.repository.renew_lease(
                    source_type=source_type_str,
                    lease_token=lease_token,
                    lease_ttl_seconds=self.lease_ttl_seconds,
                )

                # 3. Extract changed items with bounded exponential retry
                def _extract():
                    try:
                        if self.batch_size:
                            return self.connector.list_changes(cursor=last_committed_cursor, limit=self.batch_size)  # type: ignore
                        return self.connector.list_changes(cursor=last_committed_cursor)
                    except TypeError:
                        return self.connector.list_changes(cursor=last_committed_cursor)

                raw_items, next_cursor = retry_with_backoff(_extract)

                if not raw_items:
                    logger.info("no_more_items_found source=%s cursor=%s", source_type_str, last_committed_cursor)
                    self.repository.complete_sync(
                        source_type=source_type_str,
                        lease_token=lease_token,
                        final_cursor=last_committed_cursor,
                    )
                    break

                logger.info("extracted_raw_items count=%d source=%s", len(raw_items), source_type_str)

                # 4. Normalize into canonical documents & extract ACLs
                docs: List[CanonicalDocument] = []
                all_acls: List[AclReference] = []

                for item in raw_items:
                    item_acls = self.connector.extract_acl(item)
                    all_acls.extend(item_acls)
                    doc = self.normalizer.normalize(item, item_acls)
                    if doc:
                        docs.append(doc)

                # 5. Source-aware chunking
                all_chunks: List[CanonicalChunk] = []
                for doc in docs:
                    chunks = self.chunker.chunk(doc)
                    all_chunks.extend(chunks)

                logger.info("chunked_documents docs=%d chunks=%d", len(docs), len(all_chunks))

                # 6. Generate vector embeddings for all chunks
                if all_chunks:
                    texts = [c.content for c in all_chunks]
                    embeddings = self.embedding_provider.embed_texts(texts)
                    for chunk, emb in zip(all_chunks, embeddings):
                        chunk.embedding = emb

                # 7. Extract knowledge graph entities & relationships (AD-03)
                entities, relationships = extract_entities_and_relationships(raw_items, docs)

                # 8. Persist atomic batch: records, docs, chunks, acls, entities, rels + advance cursor (SYNCING)
                self.repository.persist_sync_batch(
                    source_type=source_type_str,
                    lease_token=lease_token,
                    next_cursor=next_cursor,
                    items=raw_items,
                    docs=docs,
                    chunks=all_chunks,
                    acls=all_acls,
                    entities=entities,
                    relationships=relationships,
                )

                total_records += len(raw_items)
                total_chunks += len(all_chunks)
                prior_cursor = last_committed_cursor
                last_committed_cursor = next_cursor

                # If no batch_size set, or retrieved fewer than batch_size, or cursor didn't move, complete run
                if not self.batch_size or len(raw_items) < self.batch_size or next_cursor == prior_cursor:
                    self.repository.complete_sync(
                        source_type=source_type_str,
                        lease_token=lease_token,
                        final_cursor=last_committed_cursor,
                    )
                    break

            completed_at = datetime.now(timezone.utc)
            logger.info(
                "ingestion_pipeline_succeeded source=%s records=%d chunks=%d new_cursor=%s",
                source_type_str,
                total_records,
                total_chunks,
                last_committed_cursor,
            )

            return SyncResult(
                source_type=source_type_str,
                status="SUCCESS",
                records_ingested=total_records,
                chunks_indexed=total_chunks,
                new_cursor=last_committed_cursor,
                started_at=started_at,
                completed_at=completed_at,
            )

        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.exception("ingestion_pipeline_failed source=%s err=%s", source_type_str, error_msg)

            # Record failure in checkpoint preserving last_committed_cursor so retry resumes properly
            self.repository.fail_sync(
                source_type=source_type_str,
                lease_token=lease_token,
                error_message=error_msg,
            )

            return SyncResult(
                source_type=source_type_str,
                status="FAILED",
                records_ingested=total_records,
                chunks_indexed=total_chunks,
                new_cursor=last_committed_cursor,
                error_message=error_msg,
                started_at=started_at,
                completed_at=completed_at,
            )
