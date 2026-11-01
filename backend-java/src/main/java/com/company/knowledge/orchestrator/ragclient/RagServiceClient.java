package com.company.knowledge.orchestrator.ragclient;

import com.company.knowledge.audit.dto.AuditEventResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagAskRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagAskResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;
import com.company.knowledge.sync.dto.SyncStatusResponse;
import java.util.List;
import java.util.Map;

/**
 * The abstraction boundary between backend-java and rag-python.
 *
 * <p>Everything backend-java needs from the RAG service goes through this
 * interface.
 *
 * <p>Contract: docs/api/java-python-contract.md
 */
public interface RagServiceClient {

    /**
     * Calls POST /internal/v1/rag/health on the RAG service.
     *
     * @return the RAG service's self-reported health
     * @throws RagServiceUnavailableException if the RAG service cannot be reached or returns 5xx
     */
    RagHealthResponse ping();

    /**
     * Calls POST /internal/v1/rag/search on the RAG service.
     *
     * @param request search request with query and identity context
     * @return search response containing retrieved results
     * @throws RagServiceUnavailableException if the RAG service cannot be reached or returns 5xx
     * @throws RagClientException if the RAG service rejects the request with a 4xx error
     */
    RagSearchResponse search(RagSearchRequest request);

    /**
     * Calls POST /internal/v1/rag/ask on the RAG service.
     *
     * @param request question request with identity context
     * @return grounded RAG response containing synthesized answer and citations
     * @throws RagServiceUnavailableException if the RAG service cannot be reached or returns 5xx
     * @throws RagClientException if the RAG service rejects the request with a 4xx error
     */
    RagAskResponse ask(RagAskRequest request);

    /**
     * Calls GET /internal/v1/sync/status on the RAG service.
     *
     * @return sync status across all connectors and derived overall status
     * @throws RagServiceUnavailableException if the RAG service cannot be reached or returns 5xx
     * @throws RagClientException if the RAG service rejects the request with a 4xx error
     */
    SyncStatusResponse getSyncStatus();

    /**
     * Calls POST /internal/v1/audit/events on the RAG service to persist an audit record.
     *
     * @param userId user who performed the action
     * @param action action performed
     * @param resource target resource
     * @param details contextual metadata
     * @throws RagServiceUnavailableException if the RAG service cannot be reached or returns 5xx
     * @throws RagClientException if the RAG service rejects the request with a 4xx error
     */
    void recordAuditEvent(String userId, String action, String resource, Map<String, Object> details);

    /**
     * Calls GET /internal/v1/audit/events on the RAG service.
     *
     * @param userId optional user filter
     * @param action optional action filter
     * @param limit maximum events to retrieve
     * @return list of audit events ordered by timestamp descending
     * @throws RagServiceUnavailableException if the RAG service cannot be reached or returns 5xx
     * @throws RagClientException if the RAG service rejects the request with a 4xx error
     */
    List<AuditEventResponse> getAuditEvents(String userId, String action, int limit);
}
