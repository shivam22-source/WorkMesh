package com.company.knowledge.orchestrator.ragclient;

/**
 * Thrown when the RAG service rejects our request with a 4xx error (e.g. 422 Unprocessable Entity).
 *
 * <p>Indicates a client-side bug in backend-java (e.g. contract drift or invalid argument),
 * which maps to HTTP 500 on our public API rather than claiming the RAG service is unavailable (503).
 */
public class RagClientException extends RuntimeException {

    public RagClientException(String message) {
        super(message);
    }

    public RagClientException(String message, Throwable cause) {
        super(message, cause);
    }
}
