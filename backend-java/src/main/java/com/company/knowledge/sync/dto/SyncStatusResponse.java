package com.company.knowledge.sync.dto;

import java.util.List;

/**
 * Top-level response for GET /api/v1/sync/status.
 */
public record SyncStatusResponse(
        String overallStatus,
        List<SourceSyncStatus> sources) {
}
