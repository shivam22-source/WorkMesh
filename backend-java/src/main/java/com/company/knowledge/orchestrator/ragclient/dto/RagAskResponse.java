package com.company.knowledge.orchestrator.ragclient.dto;

import java.util.List;

/**
 * Internal wire response returned by rag-python for grounded Q&A.
 */
public record RagAskResponse(
        String question,
        String answer,
        List<RagCitationItem> citations,
        String confidence,
        String status) {
}
