package com.company.knowledge.sync;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.company.knowledge.audit.AuditService;
import com.company.knowledge.auth.CurrentUserProvider;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.common.GlobalExceptionHandler;
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
    @DisplayName("GET /api/v1/sync/status returns 200 and reports sync status across all sources")
    void getSyncStatusReportsSources() throws Exception {
        UserContext testUser = new UserContext(
                "employee_42",
                "employee_42@company.internal",
                "Alex Engineer",
                "ENGINEER",
                Set.of("group_engineering")
        );
        when(currentUserProvider.getCurrentUser()).thenReturn(testUser);

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

        verify(auditService).recordEvent("employee_42", "SYNC_STATUS", "sync_state", Map.of());
    }
}
