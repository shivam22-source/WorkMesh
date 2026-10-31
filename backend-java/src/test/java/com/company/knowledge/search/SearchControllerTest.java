package com.company.knowledge.search;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.company.knowledge.auth.CurrentUserProvider;
import com.company.knowledge.auth.UserContext;
import com.company.knowledge.common.GlobalExceptionHandler;
import com.company.knowledge.orchestrator.ragclient.RagClientException;
import com.company.knowledge.orchestrator.ragclient.RagServiceUnavailableException;
import com.company.knowledge.search.dto.AskRequest;
import com.company.knowledge.search.dto.AskResponse;
import com.company.knowledge.search.dto.CitationItem;
import com.company.knowledge.search.dto.SearchRequest;
import com.company.knowledge.search.dto.SearchResponse;
import com.company.knowledge.search.dto.SearchResultItem;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(SearchController.class)
@Import(GlobalExceptionHandler.class)
class SearchControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private SearchService searchService;

    @MockitoBean
    private CurrentUserProvider currentUserProvider;

    private final UserContext testUser = new UserContext(
            "employee_42",
            "employee_42@company.internal",
            "Alex Engineer",
            "ENGINEER",
            Set.of("group_engineering", "group_backend")
    );

    @BeforeEach
    void setUp() {
        when(currentUserProvider.getCurrentUser()).thenReturn(testUser);
    }

    @Test
    @DisplayName("POST /api/v1/search with valid query returns 200 and search results")
    void searchReturnsResults() throws Exception {
        SearchResultItem item = new SearchResultItem(
                "chunk_1",
                "doc_1",
                "GITHUB",
                "Validation Fix",
                "Fixed null checks",
                "https://github.com/company/repo/pull/1",
                "Alex Engineer",
                0.92
        );
        SearchResponse mockResponse = new SearchResponse(
                "validation",
                1,
                List.of(item),
                42L,
                "STUB"
        );

        when(searchService.search(any(SearchRequest.class), any(UserContext.class)))
                .thenReturn(mockResponse);

        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "query": "validation",
                                  "limit": 10
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.query").value("validation"))
                .andExpect(jsonPath("$.totalResults").value(1))
                .andExpect(jsonPath("$.status").value("STUB"))
                .andExpect(jsonPath("$.results[0].chunkId").value("chunk_1"))
                .andExpect(jsonPath("$.results[0].sourceType").value("GITHUB"));
    }

    @Test
    @DisplayName("POST /api/v1/search with blank query returns 400 Bad Request with ApiError shape")
    void searchWithBlankQueryReturnsBadRequest() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "query": "  "
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status").value(400))
                .andExpect(jsonPath("$.error").value("Bad Request"))
                .andExpect(jsonPath("$.message").isNotEmpty())
                .andExpect(jsonPath("$.path").value("/api/v1/search"));
    }

    @Test
    @DisplayName("POST /api/v1/ask with valid question returns 200 and grounded answer with citations")
    void askReturnsAnswer() throws Exception {
        CitationItem citation = new CitationItem(
                "GITHUB",
                "Fix validation flow",
                "https://github.com/company/repo/pull/123",
                "Updated validation logic in PR #123"
        );
        AskResponse mockResponse = new AskResponse(
                "why did validation change",
                "According to the available evidence: validation updated [1]",
                List.of(citation),
                "MEDIUM",
                "ANSWERED"
        );

        when(searchService.ask(any(AskRequest.class), any(UserContext.class)))
                .thenReturn(mockResponse);

        mockMvc.perform(post("/api/v1/ask")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "question": "why did validation change"
                                }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.question").value("why did validation change"))
                .andExpect(jsonPath("$.answer").value("According to the available evidence: validation updated [1]"))
                .andExpect(jsonPath("$.status").value("ANSWERED"))
                .andExpect(jsonPath("$.confidence").value("MEDIUM"))
                .andExpect(jsonPath("$.citations[0].sourceType").value("GITHUB"))
                .andExpect(jsonPath("$.citations[0].title").value("Fix validation flow"))
                .andExpect(jsonPath("$.citations[0].url").value("https://github.com/company/repo/pull/123"))
                .andExpect(jsonPath("$.citations[0].snippet").value("Updated validation logic in PR #123"));
    }

    @Test
    @DisplayName("POST /api/v1/ask ignores spoofed identity in public JSON body and preserves server-side UserContext")
    void askWithSpoofedIdentityInBodyUsesServerSideUserContext() throws Exception {
        AskResponse mockResponse = new AskResponse(
                "why did validation change",
                "Answer",
                Collections.emptyList(),
                "LOW",
                "ANSWERED"
        );
        when(searchService.ask(any(AskRequest.class), any(UserContext.class)))
                .thenReturn(mockResponse);

        mockMvc.perform(post("/api/v1/ask")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "question": "why did validation change",
                                  "userId": "attacker_id",
                                  "groupIds": ["admin_group"]
                                }
                                """))
                .andExpect(status().isOk());

        ArgumentCaptor<UserContext> userCaptor = ArgumentCaptor.forClass(UserContext.class);
        verify(searchService).ask(any(AskRequest.class), userCaptor.capture());

        UserContext capturedUser = userCaptor.getValue();
        assertThat(capturedUser.userId()).isEqualTo("employee_42");
        assertThat(capturedUser.groupIds()).containsExactlyInAnyOrder("group_engineering", "group_backend");
    }

    @Test
    @DisplayName("POST /api/v1/ask when RAG service is unavailable returns 503 Service Unavailable")
    void askWhenRagServiceUnavailableReturns503() throws Exception {
        when(searchService.ask(any(AskRequest.class), any(UserContext.class)))
                .thenThrow(new RagServiceUnavailableException("RAG unreachable"));

        mockMvc.perform(post("/api/v1/ask")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "question": "why did validation change"
                                }
                                """))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.status").value(503))
                .andExpect(jsonPath("$.error").value("Service Unavailable"))
                .andExpect(jsonPath("$.message").value("RAG service is currently unavailable"))
                .andExpect(jsonPath("$.path").value("/api/v1/ask"));
    }

    @Test
    @DisplayName("POST /api/v1/ask when RAG client error occurs returns 500 Internal Server Error")
    void askWhenRagClientErrorReturns500() throws Exception {
        when(searchService.ask(any(AskRequest.class), any(UserContext.class)))
                .thenThrow(new RagClientException("Invalid contract response"));

        mockMvc.perform(post("/api/v1/ask")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "question": "why did validation change"
                                }
                                """))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.status").value(500))
                .andExpect(jsonPath("$.error").value("Internal Server Error"))
                .andExpect(jsonPath("$.message").value("internal service communication error"))
                .andExpect(jsonPath("$.path").value("/api/v1/ask"));
    }

    @Test
    @DisplayName("POST /api/v1/ask with blank question returns 400 Bad Request")
    void askWithBlankQuestionReturnsBadRequest() throws Exception {
        mockMvc.perform(post("/api/v1/ask")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {
                                  "question": ""
                                }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status").value(400))
                .andExpect(jsonPath("$.path").value("/api/v1/ask"));
    }
}
