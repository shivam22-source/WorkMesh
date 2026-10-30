package com.company.knowledge.orchestrator.ragclient.dto;

import java.util.List;

/**
 * Service-to-service search response returned from rag-python.
 */
public record RagSearchResponse(
        String status,
        String query,
        int totalResults,
        List<RagSearchResultItem> results) {
}
