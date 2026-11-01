package com.company.knowledge.audit.dto;

import java.time.Instant;
import java.util.Map;

/**
 * Audit event representation for administrative inspection.
 */
public record AuditEventResponse(
        Long id,
        String userId,
        String action,
        String resource,
        Map<String, Object> details,
        String ipAddress,
        Instant timestamp) {
}
