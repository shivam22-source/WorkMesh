package com.company.knowledge.orchestrator.ragclient.dto;

import java.time.Instant;

/**
 * Request body for POST /internal/v1/rag/health.
 *
 * <p>In Phase 0 this only proves the two services agree on a wire format. Later
 * phases add the authenticated employee context here — the permission context
 * that the RAG service needs in order to filter evidence.
 */
public record RagHealthRequest(String requestedBy, Instant requestedAt) {
}
