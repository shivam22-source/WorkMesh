package com.company.knowledge.orchestrator.ragclient.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

/**
 * Internal wire response returned by rag-python for grounded Q&A.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record RagAskResponse(
        String question,
        String answer,
        List<RagCitationItem> citations,
        String confidence,
        String status) {
}
