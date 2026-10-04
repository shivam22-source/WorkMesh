package com.company.knowledge.orchestrator.ragclient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;
import java.time.Duration;
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
    @DisplayName("a 5xx from rag-python becomes RagServiceUnavailableException, not a raw client error")
    void pingMapsServerErrorToTypedException() {
        server.expect(requestTo(BASE_URL + "/internal/v1/rag/health"))
                .andRespond(withServerError());

        assertThatThrownBy(() -> client.ping())
                .isInstanceOf(RagServiceUnavailableException.class)
                .hasMessageContaining(BASE_URL);
        server.verify();
    }
}
