package com.company.knowledge.search.dto;

import java.util.List;

/**
 * Response payload for POST /api/v1/ask.
 */
public record AskResponse(
        String question,
        String answer,
        List<CitationItem> citations,
        String confidence,
        String status) {
}
