package com.company.knowledge.orchestrator.ragclient;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * Builds the single RestClient used to talk to rag-python.
 *
 * <p>Timeouts are explicit. Without them a hung RAG service would hold Java
 * request threads open indefinitely.
 *
 * <p>The request factory is pinned to {@link SimpleClientHttpRequestFactory} on
 * purpose. A bare {@code RestClient.builder()} picks the JDK HttpClient, which
 * attempts an HTTP/2 cleartext (h2c) upgrade. Uvicorn rejects that upgrade and
 * the POST body is lost, so rag-python answers 422 "Field required" for a request
 * that Java believes it sent correctly. HttpURLConnection speaks HTTP/1.1 only
 * and avoids the whole problem. This was observed live during Phase 0, not
 * inferred.
 */
@Configuration
@EnableConfigurationProperties(RagClientProperties.class)
public class RagClientConfig {

    @Bean
    public RestClient ragRestClient(RagClientProperties properties) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(properties.connectTimeout());
        requestFactory.setReadTimeout(properties.readTimeout());
        return RestClient.builder()
                .baseUrl(properties.baseUrl())
                .requestFactory(requestFactory)
                .build();
    }
}
