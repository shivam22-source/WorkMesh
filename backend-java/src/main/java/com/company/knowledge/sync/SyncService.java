package com.company.knowledge.sync;

import com.company.knowledge.sync.dto.SyncStatusResponse;

/**
 * Service for reporting connector synchronization state.
 */
public interface SyncService {

    /**
     * Get the current synchronization status across all connectors.
     *
     * @return current sync status response
     */
    SyncStatusResponse getStatus();
}
