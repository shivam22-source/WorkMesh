package com.company.knowledge.orchestrator.ragclient;

import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;

/**
 * The abstraction boundary between backend-java and rag-python.
 *
 * <p>Everything backend-java needs from the RAG service goes through this
 * interface. The only implementation in Phase 0 is
 * {@link RestClientRagServiceClient}; a later phase can swap in a different
 * transport without touching any caller.
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
}
