package com.company.knowledge.search.dto;

import java.util.List;

/**
 * Response payload for POST /api/v1/search.
 */
public record SearchResponse(
        String query,
        int totalResults,
        List<SearchResultItem> results,
        long searchTimeMs,
        String status) {
}
