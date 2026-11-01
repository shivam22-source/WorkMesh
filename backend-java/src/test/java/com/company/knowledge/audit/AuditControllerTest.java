package com.company.knowledge.audit;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.company.knowledge.audit.dto.AuditEventResponse;
import com.company.knowledge.auth.CurrentUserProvider;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.common.GlobalExceptionHandler;
import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import com.company.knowledge.orchestrator.ragclient.RagServiceUnavailableException;
import java.time.Instant;
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

@WebMvcTest(AuditController.class)
@Import(GlobalExceptionHandler.class)
class AuditControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private CurrentUserProvider currentUserProvider;

    @MockitoBean
    private RagServiceClient ragServiceClient;

    @Test
    @DisplayName("GET /api/v1/admin/audit/events returns 403 Forbidden for non-admin user")
    void nonAdminReceives403Forbidden() throws Exception {
        UserContext standardUser = new UserContext(
                "employee_42",
                "employee_42@company.internal",
                "Alex Engineer",
                "ENGINEER",
                Set.of("group_engineering")
        );
        when(currentUserProvider.getCurrentUser()).thenReturn(standardUser);

        mockMvc.perform(get("/api/v1/admin/audit/events"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.status").value(403))
                .andExpect(jsonPath("$.error").value("Forbidden"))
                .andExpect(jsonPath("$.message").value("Access denied: ADMIN role required to view audit events"));
    }

    @Test
    @DisplayName("GET /api/v1/admin/audit/events returns 200 OK and events for ADMIN user")
    void adminReceivesAuditEvents() throws Exception {
        UserContext adminUser = new UserContext(
                "employee_admin",
                "admin@company.internal",
                "Admin User",
                "ADMIN",
                Set.of("group_engineering", "group_admin")
        );
        when(currentUserProvider.getCurrentUser()).thenReturn(adminUser);

        Instant now = Instant.parse("2026-11-01T12:00:00Z");
        List<AuditEventResponse> mockEvents = List.of(
                new AuditEventResponse(1L, "employee_42", "SEARCH", "hybrid", Map.of("q", "auth"), "127.0.0.1", now),
                new AuditEventResponse(2L, "employee_admin", "SYNC_STATUS", "sync_state", Map.of(), "127.0.0.1", now)
        );
        when(ragServiceClient.getAuditEvents("employee_42", "SEARCH", 20)).thenReturn(mockEvents);

        mockMvc.perform(get("/api/v1/admin/audit/events")
                        .param("userId", "employee_42")
                        .param("action", "SEARCH")
                        .param("limit", "20"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].id").value(1))
                .andExpect(jsonPath("$[0].userId").value("employee_42"))
                .andExpect(jsonPath("$[0].action").value("SEARCH"))
                .andExpect(jsonPath("$[1].userId").value("employee_admin"));

        verify(ragServiceClient).getAuditEvents("employee_42", "SEARCH", 20);
    }

    @Test
    @DisplayName("LoggingAuditService fail-open resilience when durable RAG service is unavailable")
    void loggingAuditServiceFailsOpenOnDownstreamError() {
        RagServiceClient failingClient = org.mockito.Mockito.mock(RagServiceClient.class);
        doThrow(new RagServiceUnavailableException("Connection refused"))
                .when(failingClient).recordAuditEvent(anyString(), anyString(), anyString(), anyMap());

        LoggingAuditService auditService = new LoggingAuditService(failingClient);

        // Core requirement: Must NOT throw exception when downstream fails
        assertDoesNotThrow(() ->
                auditService.recordEvent("employee_42", "SEARCH", "hybrid_index", Map.of("query", "test"))
        );

        verify(failingClient).recordAuditEvent(eq("employee_42"), eq("SEARCH"), eq("hybrid_index"), anyMap());
    }
}
