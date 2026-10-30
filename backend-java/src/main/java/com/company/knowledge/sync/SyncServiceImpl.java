package com.company.knowledge.sync;

import com.company.knowledge.sync.dto.SourceSyncStatus;
import com.company.knowledge.sync.dto.SyncStatusResponse;
import java.util.List;
import org.springframework.stereotype.Service;

/**
 * Phase 1 implementation returning the baseline sync state for configured sources.
 *
 * <p>In Phase 5, this will read from the canonical sync_state PostgreSQL table.
 */
@Service
public class SyncServiceImpl implements SyncService {

    @Override
    public SyncStatusResponse getStatus() {
        List<SourceSyncStatus> sources = List.of(
                new SourceSyncStatus("GITHUB", "IDLE", null, null, null, 0, null),
                new SourceSyncStatus("SLACK", "IDLE", null, null, null, 0, null),
                new SourceSyncStatus("EMAIL", "IDLE", null, null, null, 0, null)
        );
        return new SyncStatusResponse("IDLE", sources);
    }
}
