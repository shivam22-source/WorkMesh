package com.company.knowledge.audit;

import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Audit service implementation that writes structured log lines and persists
 * durable audit records to PostgreSQL via the internal RAG service.
 *
 * <p>Fail-open reliability design: Application logging (SLF4J) is an operational fallback
 * and is not guaranteed durable or immutable. PostgreSQL serves as the durable audit store.
 * If durable audit persistence over HTTP encounters network timeouts or RAG service downtime,
 * an operational warning is logged and the primary user flow (search/ask) continues uninterrupted.
 */
@Service
public class LoggingAuditService implements AuditService {

    private static final Logger log = LoggerFactory.getLogger(LoggingAuditService.class);

    private final RagServiceClient ragServiceClient;

    public LoggingAuditService(RagServiceClient ragServiceClient) {
        this.ragServiceClient = ragServiceClient;
    }

    @Override
    public void recordEvent(String userId, String action, String resource, Map<String, Object> details) {
        log.info("audit_event user_id={} action={} resource={} details={}",
                userId, action, resource, details);
        try {
            ragServiceClient.recordAuditEvent(userId, action, resource, details);
        } catch (Exception ex) {
            log.warn("durable_audit_persistence_failed user_id={} action={} err={}",
                    userId, action, ex.getMessage());
        }
    }
}
