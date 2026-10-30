package com.company.knowledge.audit;

import java.util.Map;

/**
 * Service boundary for recording system and user audit events.
 */
public interface AuditService {

    /**
     * Record an audit event.
     *
     * @param userId user who performed the action
     * @param action action name (e.g. SEARCH, ASK, SYNC_STATUS)
     * @param resource target resource or identifier
     * @param details contextual metadata
     */
    void recordEvent(String userId, String action, String resource, Map<String, Object> details);
}
