package com.company.knowledge.orchestrator.ragclient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withBadRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;
import java.time.Duration;
import java.util.List;
import java.util.Set;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

/**
 * Offline contract test: no Python process and no network required.
 *
 * <p>This is the guard that catches Java/Python DTO drift on the Java side.
 */
class RestClientRagServiceClientTest {

    private static final String BASE_URL = "http://rag-python.test";

    private MockRestServiceServer server;
    private RagServiceClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl(BASE_URL);
        server = MockRestServiceServer.bindTo(builder).build();
        client = new RestClientRagServiceClient(
                builder.build(),
                new RagClientProperties(BASE_URL, Duration.ofSeconds(2), Duration.ofSeconds(5)));
    }

    @Test
    @DisplayName("ping() posts to the documented contract path and maps the response")
    void pingCallsContractEndpoint() {
        server.expect(requestTo(BASE_URL + "/internal/v1/rag/health"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.requestedBy").value("backend-java"))
                .andRespond(withSuccess(
                        """
                        {
                          "status": "ok",
                          "service": "rag-python",
                          "contractVersion": "v1",
                          "message": "contract stub alive"
                        }
                        """,
                        MediaType.APPLICATION_JSON));

        RagHealthResponse response = client.ping();

        assertThat(response.status()).isEqualTo("ok");
        assertThat(response.service()).isEqualTo("rag-python");
        assertThat(response.contractVersion()).isEqualTo("v1");
        assertThat(response.message()).isEqualTo("contract stub alive");
        server.verify();
    }

    @Test
    @DisplayName("a 5xx from rag-python on ping becomes RagServiceUnavailableException")
    void pingMapsServerErrorToTypedException() {
        server.expect(requestTo(BASE_URL + "/internal/v1/rag/health"))
                .andRespond(withServerError());

        assertThatThrownBy(() -> client.ping())
                .isInstanceOf(RagServiceUnavailableException.class)
                .hasMessageContaining(BASE_URL);
        server.verify();
    }

    @Test
    @DisplayName("search() posts to documented contract path with identity context")
    void searchCallsContractEndpointAndMapsResponse() {
        server.expect(requestTo(BASE_URL + "/internal/v1/rag/search"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.query").value("why did validation change"))
                .andExpect(jsonPath("$.userId").value("employee_42"))
                .andExpect(jsonPath("$.groupIds[0]").value("group_engineering"))
                .andExpect(jsonPath("$.limit").value(10))
                .andRespond(withSuccess(
                        """
                        {
                          "status": "ok",
                          "query": "why did validation change",
                          "totalResults": 1,
                          "results": [
                            {
                              "chunkId": "chunk_1",
                              "documentId": "doc_1",
                              "sourceType": "GITHUB",
                              "title": "Fix validation flow",
                              "snippet": "Updated validation logic in PR #123",
                              "sourceUrl": "https://github.com/company/repo/pull/123",
                              "author": "Alex Engineer",
                              "score": 0.95
                            }
                          ]
                        }
                        """,
                        MediaType.APPLICATION_JSON));

        RagSearchRequest request = new RagSearchRequest(
                "why did validation change",
                "employee_42",
                Set.of("group_engineering"),
                10,
                List.of("GITHUB")
        );

        RagSearchResponse response = client.search(request);

        assertThat(response.status()).isEqualTo("ok");
        assertThat(response.query()).isEqualTo("why did validation change");
        assertThat(response.totalResults()).isEqualTo(1);
        assertThat(response.results()).hasSize(1);
        assertThat(response.results().get(0).chunkId()).isEqualTo("chunk_1");
        assertThat(response.results().get(0).sourceType()).isEqualTo("GITHUB");
        server.verify();
    }

    @Test
    @DisplayName("a 4xx from rag-python on search becomes RagClientException (client bug in Java)")
    void searchMaps4xxToRagClientException() {
        server.expect(requestTo(BASE_URL + "/internal/v1/rag/search"))
                .andRespond(withBadRequest());

        RagSearchRequest request = new RagSearchRequest(
                "bad request",
                "employee_42",
                Set.of(),
                10,
                null
        );

        assertThatThrownBy(() -> client.search(request))
                .isInstanceOf(RagClientException.class);
        server.verify();
    }

    @Test
    @DisplayName("a 5xx from rag-python on search becomes RagServiceUnavailableException")
    void searchMaps5xxToRagServiceUnavailableException() {
        server.expect(requestTo(BASE_URL + "/internal/v1/rag/search"))
                .andRespond(withServerError());

        RagSearchRequest request = new RagSearchRequest(
                "query",
                "employee_42",
                Set.of(),
                10,
                null
        );

        assertThatThrownBy(() -> client.search(request))
                .isInstanceOf(RagServiceUnavailableException.class);
        server.verify();
    }
}
