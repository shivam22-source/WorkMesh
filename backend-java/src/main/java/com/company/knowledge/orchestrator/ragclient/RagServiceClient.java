package com.company.knowledge.orchestrator.ragclient;

import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;

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
}
