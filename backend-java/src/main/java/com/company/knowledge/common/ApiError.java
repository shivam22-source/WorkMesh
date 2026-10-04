package com.company.knowledge.common;

import java.time.Instant;

/**
 * Single error shape for every non-2xx response produced by backend-java.
 *
 * <p>Deliberately mirrors the Python service error shape so a client sees one
 * contract across both services. See docs/api/java-python-contract.md.
 */
public record ApiError(
        Instant timestamp,
        int status,
        String error,
        String message,
        String path,
        String traceId) {
}
