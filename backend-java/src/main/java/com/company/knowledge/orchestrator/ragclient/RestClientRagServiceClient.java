package com.company.knowledge.orchestrator.ragclient;

import com.company.knowledge.orchestrator.ragclient.dto.RagAskRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagAskResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagHealthRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;
import java.time.Instant;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * HTTP implementation of {@link RagServiceClient} using Spring's RestClient.
 *
 * <p>Distinguishes 4xx errors (client bug in backend-java -> {@link RagClientException})
 * from 5xx/network errors (RAG service down -> {@link RagServiceUnavailableException}).
 */
@Component
public class RestClientRagServiceClient implements RagServiceClient {

    private static final Logger log = LoggerFactory.getLogger(RestClientRagServiceClient.class);
    private static final String PING_PATH = "/internal/v1/rag/health";
    private static final String SEARCH_PATH = "/internal/v1/rag/search";
    private static final String ASK_PATH = "/internal/v1/rag/ask";

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
                    .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                        throw new RagClientException(
                                "rag service at " + baseUrl + " returned client error " + res.getStatusCode() + " on " + PING_PATH);
                    })
                    .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service at " + baseUrl + " returned server error " + res.getStatusCode() + " on " + PING_PATH);
                    })
                    .body(RagHealthResponse.class);

            if (response == null) {
                throw new RagServiceUnavailableException(
                        "rag service " + baseUrl + PING_PATH + " returned an empty body");
            }
            return response;
        } catch (HttpClientErrorException ex) {
            log.error("rag_client_error base_url={} path={} status={}", baseUrl, PING_PATH, ex.getStatusCode());
            throw new RagClientException("rag service at " + baseUrl + " rejected request: " + ex.getMessage(), ex);
        } catch (HttpServerErrorException | ResourceAccessException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, PING_PATH);
            throw new RagServiceUnavailableException("rag service unreachable at " + baseUrl, ex);
        } catch (RestClientException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, PING_PATH);
            throw new RagServiceUnavailableException("rag service error at " + baseUrl, ex);
        }
    }

    @Override
    public RagSearchResponse search(RagSearchRequest request) {
        try {
            RagSearchResponse response = restClient
                    .post()
                    .uri(SEARCH_PATH)
                    .body(request)
                    .retrieve()
                    .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                        throw new RagClientException(
                                "rag service at " + baseUrl + " returned client error " + res.getStatusCode() + " on " + SEARCH_PATH);
                    })
                    .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service at " + baseUrl + " returned server error " + res.getStatusCode() + " on " + SEARCH_PATH);
                    })
                    .body(RagSearchResponse.class);

            if (response == null) {
                throw new RagServiceUnavailableException(
                        "rag service " + baseUrl + SEARCH_PATH + " returned an empty body");
            }
            return response;
        } catch (HttpClientErrorException ex) {
            log.error("rag_client_error base_url={} path={} status={}", baseUrl, SEARCH_PATH, ex.getStatusCode());
            throw new RagClientException("rag service at " + baseUrl + " rejected search request: " + ex.getMessage(), ex);
        } catch (HttpServerErrorException | ResourceAccessException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, SEARCH_PATH);
            throw new RagServiceUnavailableException("rag service unreachable at " + baseUrl, ex);
        } catch (RestClientException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, SEARCH_PATH);
            throw new RagServiceUnavailableException("rag service error at " + baseUrl, ex);
        }
    }

    @Override
    public RagAskResponse ask(RagAskRequest request) {
        try {
            RagAskResponse response = restClient
                    .post()
                    .uri(ASK_PATH)
                    .body(request)
                    .retrieve()
                    .onStatus(HttpStatusCode::is3xxRedirection, (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service returned unexpected redirect status " + res.getStatusCode() + " on " + ASK_PATH);
                    })
                    .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                        throw new RagClientException(
                                "rag service at " + baseUrl + " returned client error " + res.getStatusCode() + " on " + ASK_PATH);
                    })
                    .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service at " + baseUrl + " returned server error " + res.getStatusCode() + " on " + ASK_PATH);
                    })
                    .onStatus(status -> !status.isSameCodeAs(HttpStatus.OK), (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service returned unexpected status " + res.getStatusCode() + " on " + ASK_PATH);
                    })
                    .body(RagAskResponse.class);

            if (response == null) {
                throw new RagServiceUnavailableException(
                        "rag service " + baseUrl + ASK_PATH + " returned an empty body");
            }
            return response;
        } catch (HttpClientErrorException ex) {
            log.error("rag_client_error base_url={} path={} status={}", baseUrl, ASK_PATH, ex.getStatusCode());
            throw new RagClientException("rag service at " + baseUrl + " rejected ask request: " + ex.getMessage(), ex);
        } catch (HttpServerErrorException | ResourceAccessException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, ASK_PATH);
            throw new RagServiceUnavailableException("rag service unreachable at " + baseUrl, ex);
        } catch (RestClientException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, ASK_PATH);
            throw new RagServiceUnavailableException("rag service error at " + baseUrl, ex);
        }
    }
}
