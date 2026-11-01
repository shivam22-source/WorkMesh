package com.company.knowledge.sync;

import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import com.company.knowledge.sync.dto.SourceSyncStatus;
import com.company.knowledge.sync.dto.SyncStatusResponse;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Sync service implementation querying real connector sync status from PostgreSQL
 * via the internal RAG service.
 */
@Service
public class SyncServiceImpl implements SyncService {

    private static final Logger log = LoggerFactory.getLogger(SyncServiceImpl.class);

    private final RagServiceClient ragServiceClient;

    public SyncServiceImpl(RagServiceClient ragServiceClient) {
        this.ragServiceClient = ragServiceClient;
    }

    @Override
    public SyncStatusResponse getStatus() {
        try {
            return ragServiceClient.getSyncStatus();
        } catch (Exception ex) {
            log.warn("sync_status_rag_service_fallback err={}", ex.getMessage());
            List<SourceSyncStatus> fallbackSources = List.of(
                    new SourceSyncStatus("GITHUB", "UNAVAILABLE", null, null, null, 0, "RAG service unavailable"),
                    new SourceSyncStatus("SLACK", "UNAVAILABLE", null, null, null, 0, "RAG service unavailable"),
                    new SourceSyncStatus("EMAIL", "UNAVAILABLE", null, null, null, 0, "RAG service unavailable")
            );
            return new SyncStatusResponse("UNAVAILABLE", fallbackSources);
        }
    }
}
