package com.company.knowledge.orchestrator.ragclient.dto;

/**
 * Internal wire citation item returned by rag-python.
 */
public record RagCitationItem(
        String sourceType,
        String title,
        String url,
        String snippet) {
}
