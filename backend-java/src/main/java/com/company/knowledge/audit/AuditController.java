package com.company.knowledge.audit;

import com.company.knowledge.audit.dto.AuditEventResponse;
import com.company.knowledge.auth.CurrentUserProvider;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.common.AccessDeniedException;
import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Administrative REST endpoint exposing recent audit events.
 *
 * <p>Security Notice: In development/test environments, passing {@code X-User-Id: employee_admin}
 * simulates an administrator identity via {@code DeterministicUserProvider}. This header-based
 * mechanism is strictly a development simulation and does not constitute secure authentication.
 * Production environments must rely on a verified identity provider and authenticated claims
 * establishing the verified ADMIN role.
 */
@RestController
@RequestMapping("/api/v1/admin/audit")
public class AuditController {

    private final CurrentUserProvider currentUserProvider;
    private final RagServiceClient ragServiceClient;

    public AuditController(
            CurrentUserProvider currentUserProvider,
            RagServiceClient ragServiceClient) {
        this.currentUserProvider = currentUserProvider;
        this.ragServiceClient = ragServiceClient;
    }

    @GetMapping("/events")
    public ResponseEntity<List<AuditEventResponse>> getAuditEvents(
            @RequestParam(required = false) String userId,
            @RequestParam(required = false) String action,
            @RequestParam(defaultValue = "50") int limit) {
        UserContext user = currentUserProvider.getCurrentUser();
        if (!"ADMIN".equalsIgnoreCase(user.role())) {
            throw new AccessDeniedException("Access denied: ADMIN role required to view audit events");
        }
        List<AuditEventResponse> events = ragServiceClient.getAuditEvents(userId, action, limit);
        return ResponseEntity.ok(events);
    }
}
