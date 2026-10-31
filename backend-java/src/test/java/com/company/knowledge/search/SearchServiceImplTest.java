package com.company.knowledge.search;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.company.knowledge.audit.AuditService;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.orchestrator.ragclient.RagClientException;
import com.company.knowledge.orchestrator.ragclient.RagServiceClient;
import com.company.knowledge.orchestrator.ragclient.RagServiceUnavailableException;
import com.company.knowledge.orchestrator.ragclient.dto.RagAskRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagAskResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagCitationItem;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResultItem;
import com.company.knowledge.search.dto.AskRequest;
import com.company.knowledge.search.dto.AskResponse;
import com.company.knowledge.search.dto.SearchRequest;
import com.company.knowledge.search.dto.SearchResponse;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
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
    @DisplayName("ask propagates user identity, groups, and sourceTypes to RAG service and maps citations")
    void askPropagatesIdentityAndMapsCitationsFromRag() {
        AskRequest request = new AskRequest("why did validation change", List.of("GITHUB"));

        RagCitationItem ragCitation = new RagCitationItem(
                "GITHUB",
                "Fix validation flow",
                "https://github.com/company/repo/pull/123",
                "Updated validation logic in PR #123"
        );
        RagAskResponse ragResponse = new RagAskResponse(
                "why did validation change",
                "According to the available evidence: validation updated [1]",
                List.of(ragCitation),
                "MEDIUM",
                "ANSWERED"
        );

        when(ragServiceClient.ask(any(RagAskRequest.class))).thenReturn(ragResponse);

        AskResponse response = searchService.ask(request, testUser);

        ArgumentCaptor<RagAskRequest> captor = ArgumentCaptor.forClass(RagAskRequest.class);
        verify(ragServiceClient).ask(captor.capture());

        RagAskRequest sent = captor.getValue();
        assertThat(sent.question()).isEqualTo("why did validation change");
        assertThat(sent.userId()).isEqualTo("employee_42");
        assertThat(sent.groupIds()).containsExactlyInAnyOrder("group_engineering", "group_backend");
        assertThat(sent.sourceTypes()).containsExactly("GITHUB");

        assertThat(response.question()).isEqualTo("why did validation change");
        assertThat(response.answer()).contains("validation updated [1]");
        assertThat(response.confidence()).isEqualTo("MEDIUM");
        assertThat(response.status()).isEqualTo("ANSWERED");
        assertThat(response.citations()).hasSize(1);
        assertThat(response.citations().get(0).sourceType()).isEqualTo("GITHUB");
        assertThat(response.citations().get(0).title()).isEqualTo("Fix validation flow");
        assertThat(response.citations().get(0).url()).isEqualTo("https://github.com/company/repo/pull/123");
        assertThat(response.citations().get(0).snippet()).isEqualTo("Updated validation logic in PR #123");
    }

    @Test
    @DisplayName("ask records audit event before calling RAG service")
    void askAuditTimingExecutedBeforeRagCall() {
        AskRequest request = new AskRequest("why did validation change", null);
        RagAskResponse ragResponse = new RagAskResponse(
                "why did validation change",
                "Answer",
                Collections.emptyList(),
                "MEDIUM",
                "ANSWERED"
        );
        when(ragServiceClient.ask(any(RagAskRequest.class))).thenReturn(ragResponse);

        searchService.ask(request, testUser);

        InOrder inOrder = inOrder(auditService, ragServiceClient);
        inOrder.verify(auditService).recordEvent(
                eq("employee_42"),
                eq("ASK"),
                eq("knowledge_assistant"),
                any(Map.class)
        );
        inOrder.verify(ragServiceClient).ask(any(RagAskRequest.class));
    }

    @Test
    @DisplayName("ask audit event remains recorded when RAG service throws exception")
    void askAuditRemainsRecordedWhenRagClientThrowsException() {
        AskRequest request = new AskRequest("failing question", null);
        when(ragServiceClient.ask(any(RagAskRequest.class)))
                .thenThrow(new RagServiceUnavailableException("RAG unreachable"));

        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagServiceUnavailableException.class);

        verify(auditService).recordEvent(
                eq("employee_42"),
                eq("ASK"),
                eq("knowledge_assistant"),
                any(Map.class)
        );
    }

    @Test
    @DisplayName("ask rejects null question in RAG response")
    void askRejectsNullQuestion() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse(null, "a", Collections.emptyList(), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects blank question in RAG response")
    void askRejectsBlankQuestion() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("   ", "a", Collections.emptyList(), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects null answer in RAG response")
    void askRejectsNullAnswer() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", null, Collections.emptyList(), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects blank answer in RAG response")
    void askRejectsBlankAnswer() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "  \t\n ", Collections.emptyList(), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects null confidence in RAG response")
    void askRejectsNullConfidence() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", Collections.emptyList(), null, "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects blank confidence in RAG response")
    void askRejectsBlankConfidence() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", Collections.emptyList(), "   ", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects null status in RAG response")
    void askRejectsNullStatus() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", Collections.emptyList(), "LOW", null)
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects blank status in RAG response")
    void askRejectsBlankStatus() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", Collections.emptyList(), "LOW", "  ")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects null citations list in RAG response")
    void askRejectsNullCitationsList() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", null, "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects null citation entry in citations list")
    void askRejectsNullCitationEntry() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", Collections.singletonList(null), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects citation entry with null or blank sourceType")
    void askRejectsCitationWithNullOrBlankSourceType() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem(null, "t", "http", "s")), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);

        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem("  ", "t", "http", "s")), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects citation entry with null or blank title")
    void askRejectsCitationWithNullOrBlankTitle() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem("SRC", null, "http", "s")), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);

        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem("SRC", " ", "http", "s")), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects citation entry with null or blank url")
    void askRejectsCitationWithNullOrBlankUrl() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem("SRC", "t", null, "s")), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);

        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem("SRC", "t", "  ", "s")), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask rejects citation entry with null or blank snippet")
    void askRejectsCitationWithNullOrBlankSnippet() {
        AskRequest request = new AskRequest("q", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem("SRC", "t", "http", null)), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);

        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse("q", "a", List.of(new RagCitationItem("SRC", "t", "http", "  ")), "LOW", "ANSWERED")
        );
        assertThatThrownBy(() -> searchService.ask(request, testUser))
                .isInstanceOf(RagClientException.class);
    }

    @Test
    @DisplayName("ask handles valid INSUFFICIENT_EVIDENCE response with empty citations")
    void askHandlesInsufficientEvidenceWithEmptyCitations() {
        AskRequest request = new AskRequest("unknown topic", null);
        when(ragServiceClient.ask(any())).thenReturn(
                new RagAskResponse(
                        "unknown topic",
                        "I do not have sufficient authorized documentation or evidence to answer this question.",
                        Collections.emptyList(),
                        "LOW",
                        "INSUFFICIENT_EVIDENCE"
                )
        );

        AskResponse response = searchService.ask(request, testUser);

        assertThat(response.question()).isEqualTo("unknown topic");
        assertThat(response.status()).isEqualTo("INSUFFICIENT_EVIDENCE");
        assertThat(response.confidence()).isEqualTo("LOW");
        assertThat(response.citations()).isEmpty();
    }
}
