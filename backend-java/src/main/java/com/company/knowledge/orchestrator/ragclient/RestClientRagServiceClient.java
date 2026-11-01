package com.company.knowledge.orchestrator.ragclient;

import com.company.knowledge.audit.dto.AuditEventResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagAskRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagAskResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagHealthRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagHealthResponse;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchRequest;
import com.company.knowledge.orchestrator.ragclient.dto.RagSearchResponse;
import com.company.knowledge.sync.dto.SyncStatusResponse;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
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
    private static final String SYNC_STATUS_PATH = "/internal/v1/sync/status";
    private static final String AUDIT_EVENTS_PATH = "/internal/v1/audit/events";

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

    @Override
    public SyncStatusResponse getSyncStatus() {
        try {
            SyncStatusResponse response = restClient
                    .get()
                    .uri(SYNC_STATUS_PATH)
                    .retrieve()
                    .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                        throw new RagClientException(
                                "rag service at " + baseUrl + " returned client error " + res.getStatusCode() + " on " + SYNC_STATUS_PATH);
                    })
                    .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service at " + baseUrl + " returned server error " + res.getStatusCode() + " on " + SYNC_STATUS_PATH);
                    })
                    .body(SyncStatusResponse.class);

            if (response == null) {
                throw new RagServiceUnavailableException(
                        "rag service " + baseUrl + SYNC_STATUS_PATH + " returned an empty body");
            }
            return response;
        } catch (HttpClientErrorException ex) {
            log.error("rag_client_error base_url={} path={} status={}", baseUrl, SYNC_STATUS_PATH, ex.getStatusCode());
            throw new RagClientException("rag service at " + baseUrl + " rejected sync status request: " + ex.getMessage(), ex);
        } catch (HttpServerErrorException | ResourceAccessException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, SYNC_STATUS_PATH);
            throw new RagServiceUnavailableException("rag service unreachable at " + baseUrl, ex);
        } catch (RestClientException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, SYNC_STATUS_PATH);
            throw new RagServiceUnavailableException("rag service error at " + baseUrl, ex);
        }
    }

    @Override
    public void recordAuditEvent(String userId, String action, String resource, Map<String, Object> details) {
        Map<String, Object> body = new HashMap<>();
        body.put("userId", userId);
        body.put("action", action);
        if (resource != null) {
            body.put("resource", resource);
        }
        if (details != null) {
            body.put("details", details);
        }
        try {
            restClient
                    .post()
                    .uri(AUDIT_EVENTS_PATH)
                    .body(body)
                    .retrieve()
                    .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                        throw new RagClientException(
                                "rag service at " + baseUrl + " returned client error " + res.getStatusCode() + " on " + AUDIT_EVENTS_PATH);
                    })
                    .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service at " + baseUrl + " returned server error " + res.getStatusCode() + " on " + AUDIT_EVENTS_PATH);
                    })
                    .toBodilessEntity();
        } catch (HttpClientErrorException ex) {
            log.error("rag_client_error base_url={} path={} status={}", baseUrl, AUDIT_EVENTS_PATH, ex.getStatusCode());
            throw new RagClientException("rag service at " + baseUrl + " rejected audit record request: " + ex.getMessage(), ex);
        } catch (HttpServerErrorException | ResourceAccessException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, AUDIT_EVENTS_PATH);
            throw new RagServiceUnavailableException("rag service unreachable at " + baseUrl, ex);
        } catch (RestClientException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, AUDIT_EVENTS_PATH);
            throw new RagServiceUnavailableException("rag service error at " + baseUrl, ex);
        }
    }

    @Override
    public List<AuditEventResponse> getAuditEvents(String userId, String action, int limit) {
        try {
            List<AuditEventResponse> response = restClient
                    .get()
                    .uri(uriBuilder -> {
                        var b = uriBuilder.path(AUDIT_EVENTS_PATH).queryParam("limit", limit);
                        if (userId != null && !userId.isBlank()) {
                            b.queryParam("userId", userId);
                        }
                        if (action != null && !action.isBlank()) {
                            b.queryParam("action", action);
                        }
                        return b.build();
                    })
                    .retrieve()
                    .onStatus(HttpStatusCode::is4xxClientError, (req, res) -> {
                        throw new RagClientException(
                                "rag service at " + baseUrl + " returned client error " + res.getStatusCode() + " on " + AUDIT_EVENTS_PATH);
                    })
                    .onStatus(HttpStatusCode::is5xxServerError, (req, res) -> {
                        throw new RagServiceUnavailableException(
                                "rag service at " + baseUrl + " returned server error " + res.getStatusCode() + " on " + AUDIT_EVENTS_PATH);
                    })
                    .body(new ParameterizedTypeReference<List<AuditEventResponse>>() {});

            return response != null ? response : List.of();
        } catch (HttpClientErrorException ex) {
            log.error("rag_client_error base_url={} path={} status={}", baseUrl, AUDIT_EVENTS_PATH, ex.getStatusCode());
            throw new RagClientException("rag service at " + baseUrl + " rejected audit events request: " + ex.getMessage(), ex);
        } catch (HttpServerErrorException | ResourceAccessException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, AUDIT_EVENTS_PATH);
            throw new RagServiceUnavailableException("rag service unreachable at " + baseUrl, ex);
        } catch (RestClientException ex) {
            log.warn("rag_service_unavailable base_url={} path={}", baseUrl, AUDIT_EVENTS_PATH);
            throw new RagServiceUnavailableException("rag service error at " + baseUrl, ex);
        }
    }
}
