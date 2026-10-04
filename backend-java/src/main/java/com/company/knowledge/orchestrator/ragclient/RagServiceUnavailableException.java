package com.company.knowledge.orchestrator.ragclient;

/**
 * Raised when the RAG service is unreachable or answers with a server error.
 *
 * <p>Kept as a distinct type so callers can decide between "retry later" and
 * "fail the request" instead of catching a generic exception.
 */
public class RagServiceUnavailableException extends RuntimeException {

    public RagServiceUnavailableException(String message) {
        super(message);
    }

    public RagServiceUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
