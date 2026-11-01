package com.company.knowledge.sync;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.company.knowledge.audit.AuditService;
import com.company.knowledge.auth.CurrentUserProvider;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.common.GlobalExceptionHandler;
import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import com.company.knowledge.orchestrator.ragclient.RagServiceUnavailableException;
import com.company.knowledge.sync.dto.SourceSyncStatus;
import com.company.knowledge.sync.dto.SyncStatusResponse;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(SyncController.class)
@Import(GlobalExceptionHandler.class)
class SyncControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private SyncService syncService;

    @MockitoBean
    private CurrentUserProvider currentUserProvider;

    @MockitoBean
    private AuditService auditService;

    @Test
    @DisplayName("GET /api/v1/sync/status returns 403 Forbidden for non-admin user")
    void getSyncStatusForbiddenForNonAdmin() throws Exception {
        UserContext standardUser = new UserContext(
                "employee_42",
                "employee_42@company.internal",
                "Alex Engineer",
                "ENGINEER",
                Set.of("group_engineering")
        );
        when(currentUserProvider.getCurrentUser()).thenReturn(standardUser);

        mockMvc.perform(get("/api/v1/sync/status"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.status").value(403))
                .andExpect(jsonPath("$.error").value("Forbidden"))
                .andExpect(jsonPath("$.message").value("Access denied: ADMIN role required to view sync status"));
    }

    @Test
    @DisplayName("GET /api/v1/admin/sync/status returns 403 Forbidden for non-admin user")
    void getAdminSyncStatusForbiddenForNonAdmin() throws Exception {
        UserContext standardUser = new UserContext(
                "employee_42",
                "employee_42@company.internal",
                "Alex Engineer",
                "ENGINEER",
                Set.of("group_engineering")
        );
        when(currentUserProvider.getCurrentUser()).thenReturn(standardUser);

        mockMvc.perform(get("/api/v1/admin/sync/status"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.status").value(403))
                .andExpect(jsonPath("$.error").value("Forbidden"));
    }

    @Test
    @DisplayName("GET /api/v1/sync/status returns 200 and reports sync status for ADMIN user")
    void getSyncStatusReportsSourcesForAdmin() throws Exception {
        UserContext adminUser = new UserContext(
                "employee_admin",
                "admin@company.internal",
                "Admin User",
                "ADMIN",
                Set.of("group_engineering", "group_admin")
        );
        when(currentUserProvider.getCurrentUser()).thenReturn(adminUser);

        SyncStatusResponse mockResponse = new SyncStatusResponse(
                "IDLE",
                List.of(
                        new SourceSyncStatus("GITHUB", "IDLE", null, null, null, 0, null),
                        new SourceSyncStatus("SLACK", "IDLE", null, null, null, 0, null),
                        new SourceSyncStatus("EMAIL", "IDLE", null, null, null, 0, null)
                )
        );
        when(syncService.getStatus()).thenReturn(mockResponse);

        mockMvc.perform(get("/api/v1/sync/status"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.overallStatus").value("IDLE"))
                .andExpect(jsonPath("$.sources").isArray())
                .andExpect(jsonPath("$.sources[0].sourceType").value("GITHUB"))
                .andExpect(jsonPath("$.sources[1].sourceType").value("SLACK"))
                .andExpect(jsonPath("$.sources[2].sourceType").value("EMAIL"));

        verify(auditService).recordEvent("employee_admin", "SYNC_STATUS", "sync_state", Map.of());
    }

    @Test
    @DisplayName("GET /api/v1/admin/sync/status returns 200 and reports sync status for ADMIN user")
    void getAdminSyncStatusReportsSourcesForAdmin() throws Exception {
        UserContext adminUser = new UserContext(
                "employee_admin",
                "admin@company.internal",
                "Admin User",
                "ADMIN",
                Set.of("group_engineering", "group_admin")
        );
        when(currentUserProvider.getCurrentUser()).thenReturn(adminUser);

        SyncStatusResponse mockResponse = new SyncStatusResponse(
                "IDLE",
                List.of(
                        new SourceSyncStatus("GITHUB", "IDLE", null, null, null, 0, null),
                        new SourceSyncStatus("SLACK", "IDLE", null, null, null, 0, null),
                        new SourceSyncStatus("EMAIL", "IDLE", null, null, null, 0, null)
                )
        );
        when(syncService.getStatus()).thenReturn(mockResponse);

        mockMvc.perform(get("/api/v1/admin/sync/status"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.overallStatus").value("IDLE"));
    }

    @Test
    @DisplayName("SyncServiceImpl returns UNAVAILABLE when downstream RAG service is unreachable")
    void syncServiceImplFallbackReturnsUnavailable() {
        RagServiceClient failingClient = mock(RagServiceClient.class);
        when(failingClient.getSyncStatus())
                .thenThrow(new RagServiceUnavailableException("Connection refused"));

        SyncServiceImpl service = new SyncServiceImpl(failingClient);
        SyncStatusResponse response = service.getStatus();

        assertEquals("UNAVAILABLE", response.overallStatus());
        assertEquals(3, response.sources().size());
        for (var source : response.sources()) {
            assertEquals("UNAVAILABLE", source.status());
            assertEquals("RAG service unavailable", source.errorMessage());
        }
    }
}
