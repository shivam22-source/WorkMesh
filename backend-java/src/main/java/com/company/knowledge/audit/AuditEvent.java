package com.company.knowledge.audit;

import java.time.Instant;
import java.util.Map;

/**
 * Immutable audit record representing a security or user action.
 */
public record AuditEvent(
        String userId,
        String action,
        String resource,
        Map<String, Object> details,
        Instant timestamp) {

    public static AuditEvent create(String userId, String action, String resource, Map<String, Object> details) {
        return new AuditEvent(userId, action, resource, details, Instant.now());
    }
}
