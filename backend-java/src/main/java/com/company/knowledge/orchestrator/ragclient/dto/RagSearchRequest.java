package com.company.knowledge.orchestrator.ragclient.dto;

import java.util.List;
import java.util.Set;

/**
 * Service-to-service search request sent to rag-python.
 *
 * <p>Carries the authenticated user identity and resolved groupIds so rag-python
 * can enforce ACL constraints directly in SQL before building retrieval evidence.
 */
public record RagSearchRequest(
        String query,
        String userId,
        Set<String> groupIds,
        int limit,
        List<String> sourceTypes) {
}
