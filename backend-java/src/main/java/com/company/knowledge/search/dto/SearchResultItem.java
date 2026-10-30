package com.company.knowledge.search.dto;

/**
 * A single retrieved result item returned in the search response.
 */
public record SearchResultItem(
        String chunkId,
        String documentId,
        String sourceType,
        String title,
        String snippet,
        String sourceUrl,
        String author,
        double score) {
}
