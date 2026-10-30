package com.company.knowledge.search;

import com.company.knowledge.audit.AuditService;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;
import com.company.knowledge.search.dto.AskRequest;
import com.company.knowledge.search.dto.AskResponse;
import com.company.knowledge.search.dto.CitationItem;
import com.company.knowledge.search.dto.SearchRequest;
import com.company.knowledge.search.dto.SearchResponse;
import com.company.knowledge.search.dto.SearchResultItem;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Orchestrator implementation for search and Q&A.
 *
 * <p>In Phase 1, calls the RAG service contract stub to verify end-to-end identity
 * propagation and wire agreement without performing actual vector/lexical retrieval.
 */
@Service
public class SearchServiceImpl implements SearchService {

    private static final Logger log = LoggerFactory.getLogger(SearchServiceImpl.class);

    private final RagServiceClient ragServiceClient;
    private final AuditService auditService;

    public SearchServiceImpl(RagServiceClient ragServiceClient, AuditService auditService) {
        this.ragServiceClient = ragServiceClient;
        this.auditService = auditService;
    }

    @Override
    public SearchResponse search(SearchRequest request, UserContext user) {
        long startTime = System.currentTimeMillis();
        log.info("search_initiated user_id={} groups={} query='{}'",
                user.userId(), user.groupIds(), request.query());

        auditService.recordEvent(
                user.userId(),
                "SEARCH",
                "knowledge_index",
                Map.of("query", request.query(), "limit", request.resolvedLimit())
        );

        RagSearchRequest ragRequest = new RagSearchRequest(
                request.query(),
                user.userId(),
                user.groupIds(),
                request.resolvedLimit(),
                request.sourceTypes()
        );

        RagSearchResponse ragResponse = ragServiceClient.search(ragRequest);

        List<SearchResultItem> items = ragResponse.results() != null
                ? ragResponse.results().stream()
                        .map(r -> new SearchResultItem(
                                r.chunkId(),
                                r.documentId(),
                                r.sourceType(),
                                r.title(),
                                r.snippet(),
                                r.sourceUrl(),
                                r.author(),
                                r.score()))
                        .toList()
                : Collections.emptyList();

        long elapsedMs = System.currentTimeMillis() - startTime;
        return new SearchResponse(request.query(), items.size(), items, elapsedMs, "STUB");
    }

    @Override
    public AskResponse ask(AskRequest request, UserContext user) {
        log.info("ask_initiated user_id={} question='{}'", user.userId(), request.question());

        auditService.recordEvent(
                user.userId(),
                "ASK",
                "knowledge_assistant",
                Map.of("question", request.question())
        );

        // Phase 1 stub: LLM evidence synthesis and citation extraction is Phase 4
        String answer = "Phase 1 stub: Query received for question '" + request.question()
                + "'. Actual retrieval, permission filtering, and LLM answer synthesis will be active in Phase 4.";

        List<CitationItem> citations = Collections.emptyList();
        return new AskResponse(request.question(), answer, citations, "LOW", "STUB");
    }
}
