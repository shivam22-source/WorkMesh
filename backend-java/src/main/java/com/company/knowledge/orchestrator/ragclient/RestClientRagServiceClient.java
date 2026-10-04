package com.company.knowledge.orchestrator.ragclient;

import com.company.knowledge.orchestrator.ragclient.dto.RagHealthRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * HTTP implementation of {@link RagServiceClient} using Spring's RestClient.
 *
 * <p>Every transport failure is translated into
 * {@link RagServiceUnavailableException} so no caller ever sees a raw
 * RestClient exception.
 */
@Component
public class RestClientRagServiceClient implements RagServiceClient {

    private static final Logger log = LoggerFactory.getLogger(RestClientRagServiceClient.class);
    private static final String PING_PATH = "/internal/v1/rag/health";
    private static final String CONTRACT_VERSION = "v1";

    private final RestClient restClient;
    private final String baseUrl;

    public RestClientRagServiceClient(RestClient ragRestClient, RagClientProperties properties) {
        this.restClient = ragRestClient;
        this.baseUrl = properties.baseUrl();
        log.info("rag_client_configured base_url={}", baseUrl);
    }

    @Override
    public RagHealthResponse ping() {
        RagHealthRequest request = new RagHealthRequest("backend-java", Instant.now());
        try {
            RagHealthResponse response = restClient
                    .post()
                    .uri(PING_PATH)
                    .body(request)
                    .retrieve()
                    .body(RagHealthResponse.class);
            if (response == null) {
                throw new RagServiceUnavailableException(
                        "rag service " + baseUrl + PING_PATH + " returned an empty body");
            }
            return response;
        } catch (RestClientException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, PING_PATH);
            throw new RagServiceUnavailableException(
                    "rag service unreachable at " + baseUrl, ex);
        }
    }
}
