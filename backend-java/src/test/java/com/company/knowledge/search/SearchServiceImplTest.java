package com.company.knowledge.search;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.company.knowledge.audit.AuditService;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResultItem;
import com.company.knowledge.search.dto.AskRequest;
import com.company.knowledge.search.dto.AskResponse;
import com.company.knowledge.search.dto.SearchRequest;
import com.company.knowledge.search.dto.SearchResponse;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class SearchServiceImplTest {

    @Mock
    private RagServiceClient ragServiceClient;

    @Mock
    private AuditService auditService;

    private SearchServiceImpl searchService;

    private final UserContext testUser = new UserContext(
            "employee_42",
            "employee_42@company.internal",
            "Alex Engineer",
            "ENGINEER",
            Set.of("group_engineering", "group_backend")
    );

    @BeforeEach
    void setUp() {
        searchService = new SearchServiceImpl(ragServiceClient, auditService);
    }

    @Test
    @DisplayName("search propagates user identity and groups to RAG service")
    void searchPropagatesIdentityToRag() {
        SearchRequest request = new SearchRequest("validation error", 10, List.of("GITHUB"));

        RagSearchResultItem ragItem = new RagSearchResultItem(
                "chunk_1",
                "doc_1",
                "GITHUB",
                "Validation Fix",
                "Fixed null checks",
                "https://github.com/company/repo/pull/1",
                "Alex",
                0.95
        );
        when(ragServiceClient.search(any(RagSearchRequest.class)))
                .thenReturn(new RagSearchResponse("ok", "validation error", 1, List.of(ragItem)));

        SearchResponse response = searchService.search(request, testUser);

        ArgumentCaptor<RagSearchRequest> captor = ArgumentCaptor.forClass(RagSearchRequest.class);
        verify(ragServiceClient).search(captor.capture());

        RagSearchRequest sent = captor.getValue();
        assertThat(sent.query()).isEqualTo("validation error");
        assertThat(sent.userId()).isEqualTo("employee_42");
        assertThat(sent.groupIds()).containsExactlyInAnyOrder("group_engineering", "group_backend");
        assertThat(sent.limit()).isEqualTo(10);
        assertThat(sent.sourceTypes()).containsExactly("GITHUB");

        assertThat(response.totalResults()).isEqualTo(1);
        assertThat(response.results().get(0).chunkId()).isEqualTo("chunk_1");

        verify(auditService).recordEvent(
                eq("employee_42"),
                eq("SEARCH"),
                eq("knowledge_index"),
                any(Map.class)
        );
    }

    @Test
    @DisplayName("search maps mixed GITHUB and SLACK results properly from RAG service")
    void searchMapsMixedSourcesFromRag() {
        SearchRequest request = new SearchRequest("DC-8692", 10, null);

        RagSearchResultItem githubItem = new RagSearchResultItem(
                "chunk:github:1",
                "doc:github:1",
                "GITHUB",
                "Fix validation flow",
                "PR #123 fix DC-8692",
                "https://github.com/company/repo/pull/123",
                "Alex",
                0.032
        );
        RagSearchResultItem slackItem = new RagSearchResultItem(
                "chunk:slack:1",
                "doc:slack:1",
                "SLACK",
                "Payment validation thread",
                "Discussion on DC-8692",
                "https://company.slack.com/archives/C1/p1",
                "Sam",
                0.016
        );

        when(ragServiceClient.search(any(RagSearchRequest.class)))
                .thenReturn(new RagSearchResponse("ok", "DC-8692", 2, List.of(githubItem, slackItem)));

        SearchResponse response = searchService.search(request, testUser);

        assertThat(response.totalResults()).isEqualTo(2);
        assertThat(response.results()).hasSize(2);
        assertThat(response.results().get(0).sourceType()).isEqualTo("GITHUB");
        assertThat(response.results().get(0).chunkId()).isEqualTo("chunk:github:1");
        assertThat(response.results().get(1).sourceType()).isEqualTo("SLACK");
        assertThat(response.results().get(1).chunkId()).isEqualTo("chunk:slack:1");
    }

    @Test
    @DisplayName("ask records audit event and returns structured stub")
    void askRecordsAuditAndReturnsStub() {
        AskRequest request = new AskRequest("why did validation change", List.of("GITHUB"));

        AskResponse response = searchService.ask(request, testUser);

        assertThat(response.question()).isEqualTo("why did validation change");
        assertThat(response.status()).isEqualTo("STUB");
        assertThat(response.answer()).contains("Phase 1 stub");

        verify(auditService).recordEvent(
                eq("employee_42"),
                eq("ASK"),
                eq("knowledge_assistant"),
                any(Map.class)
        );
    }
}
