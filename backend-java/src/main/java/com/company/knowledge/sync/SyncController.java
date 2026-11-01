package com.company.knowledge.sync;

import com.company.knowledge.auth.CurrentUserProvider;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.audit.AuditService;
import com.company.knowledge.common.AccessDeniedException;
import com.company.knowledge.sync.dto.SyncStatusResponse;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * REST endpoint exposing connector synchronization status for administrators.
 *
 * <p>Security Notice: In development/test environments, passing {@code X-User-Id: employee_admin}
 * simulates an administrator identity via {@code DeterministicUserProvider}. This header-based
 * mechanism is strictly a development simulation and does not constitute secure authentication.
 * Production environments must rely on a verified identity provider and authenticated claims
 * establishing the verified ADMIN role.
 */
@RestController
@RequestMapping({"/api/v1/sync", "/api/v1/admin/sync"})
public class SyncController {

    private final SyncService syncService;
    private final CurrentUserProvider currentUserProvider;
    private final AuditService auditService;

    public SyncController(
            SyncService syncService,
            CurrentUserProvider currentUserProvider,
            AuditService auditService) {
        this.syncService = syncService;
        this.currentUserProvider = currentUserProvider;
        this.auditService = auditService;
    }

    @GetMapping("/status")
    public ResponseEntity<SyncStatusResponse> getStatus() {
        UserContext user = currentUserProvider.getCurrentUser();
        if (!"ADMIN".equalsIgnoreCase(user.role())) {
            throw new AccessDeniedException("Access denied: ADMIN role required to view sync status");
        }
        auditService.recordEvent(user.userId(), "SYNC_STATUS", "sync_state", Map.of());
        return ResponseEntity.ok(syncService.getStatus());
    }
}
