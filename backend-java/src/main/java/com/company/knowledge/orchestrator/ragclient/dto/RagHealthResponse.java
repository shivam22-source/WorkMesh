package com.company.knowledge.orchestrator.ragclient.dto;

/**
 * Response body of POST /internal/v1/rag/health.
 *
 * <p>Field names and types must match app/contracts/rag_health.py in rag-python
 * exactly. A change on either side must break a test on the other side, which is
 * why rag-python has its own contract test asserting this exact shape.
 */
public record RagHealthResponse(
        String status,
        String service,
        String contractVersion,
        String message) {
}
