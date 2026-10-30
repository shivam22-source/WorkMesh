package com.company.knowledge.audit;

import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Phase 1 audit service implementation that logs structured audit lines.
 *
 * <p>In Phase 5, this will be persisted to the canonical PostgreSQL audit_events table.
 */
@Service
public class LoggingAuditService implements AuditService {

    private static final Logger log = LoggerFactory.getLogger(LoggingAuditService.class);

    @Override
    public void recordEvent(String userId, String action, String resource, Map<String, Object> details) {
        log.info("audit_event user_id={} action={} resource={} details={}",
                userId, action, resource, details);
    }
}
