package com.company.knowledge.orchestrator.ragclient.dto;

import java.util.List;
import java.util.Set;

/**
 * Internal wire request sent to rag-python for grounded Q&A.
 */
public record RagAskRequest(
        String question,
        String userId,
        Set<String> groupIds,
        List<String> sourceTypes) {
}
