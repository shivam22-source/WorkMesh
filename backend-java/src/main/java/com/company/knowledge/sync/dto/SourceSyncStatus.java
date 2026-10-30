package com.company.knowledge.sync.dto;

import java.time.Instant;

/**
 * Status of an individual source connector sync state.
 */
public record SourceSyncStatus(
        String sourceType,
        String status,
        String cursor,
        Instant lastSyncStartedAt,
        Instant lastSyncCompletedAt,
        int recordsSyncedLastRun,
        String errorMessage) {
}
