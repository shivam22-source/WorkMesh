package com.company.knowledge.search.dto;

/**
 * Citation indicating source evidence for an answer claim.
 */
public record CitationItem(
        String sourceType,
        String title,
        String url,
        String snippet) {
}
