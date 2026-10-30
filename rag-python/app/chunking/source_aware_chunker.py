"""Source-aware chunker respecting markdown and document structure."""

import math
from typing import List

from app.chunking.models import CanonicalChunk
from app.normalization.models import CanonicalDocument


class SourceAwareChunker:
    """Splits canonical documents into self-contained searchable chunks with stable IDs."""

    def __init__(self, target_chunk_chars: int = 800, min_chunk_chars: int = 150):
        self.target_chunk_chars = target_chunk_chars
        self.min_chunk_chars = min_chunk_chars

    def chunk(self, doc: CanonicalDocument) -> List[CanonicalChunk]:
        raw_sections = doc.content.split("\n\n")
        sections = [s.strip() for s in raw_sections if s.strip()]

        if not sections:
            return []

        chunks: List[str] = []
        current_buffer: List[str] = []
        current_len = 0

        for section in sections:
            sec_len = len(section)
            # If section itself exceeds target size, split lines
            if sec_len > self.target_chunk_chars:
                if current_buffer:
                    chunks.append("\n\n".join(current_buffer))
                    current_buffer = []
                    current_len = 0

                lines = section.split("\n")
                line_buf: List[str] = []
                line_len = 0
                for line in lines:
                    if line_len + len(line) > self.target_chunk_chars and line_buf:
                        chunks.append("\n".join(line_buf))
                        line_buf = []
                        line_len = 0
                    line_buf.append(line)
                    line_len += len(line) + 1
                if line_buf:
                    chunks.append("\n".join(line_buf))
                continue

            if current_len + sec_len > self.target_chunk_chars and current_buffer:
                chunks.append("\n\n".join(current_buffer))
                current_buffer = []
                current_len = 0

            current_buffer.append(section)
            current_len += sec_len + 2

        if current_buffer:
            chunks.append("\n\n".join(current_buffer))

        # Convert chunk strings into CanonicalChunk objects
        canonical_chunks: List[CanonicalChunk] = []
        for idx, text in enumerate(chunks):
            chunk_id = f"chunk:{doc.id}:{idx}"
            chunk_hash = CanonicalChunk.compute_hash(text)
            # Rough token estimate: ~4 characters per token
            token_count = max(1, math.ceil(len(text) / 4))

            chunk_meta = {
                "source_type": doc.source_type,
                "source_url": doc.url,
                "title": doc.title,
                "author": doc.author,
                "repository": doc.metadata.get("repository"),
                "ticket_ids": doc.metadata.get("ticket_ids", []),
                "chunk_index": idx,
                "total_chunks": len(chunks),
            }

            # Chunks inherit ACL references from the document
            chunk_acls = [
                acl.model_copy(update={"resource_type": "CHUNK", "resource_id": chunk_id})
                for acl in doc.acl_references
            ]

            canonical_chunks.append(
                CanonicalChunk(
                    id=chunk_id,
                    document_id=doc.id,
                    chunk_index=idx,
                    content=text,
                    token_count=token_count,
                    content_hash=chunk_hash,
                    metadata=chunk_meta,
                    acl_references=chunk_acls,
                    created_at=doc.created_at,
                )
            )

        return canonical_chunks
