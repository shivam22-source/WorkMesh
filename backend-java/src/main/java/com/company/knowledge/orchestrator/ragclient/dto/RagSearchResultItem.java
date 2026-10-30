package com.company.knowledge.orchestrator.ragclient.dto;

/**
 * A single retrieved result item returned by rag-python over the internal contract.
 */
public record RagSearchResultItem(
        String chunkId,
        String documentId,
        String sourceType,
        String title,
        String snippet,
        String sourceUrl,
        String author,
        double score) {
}
