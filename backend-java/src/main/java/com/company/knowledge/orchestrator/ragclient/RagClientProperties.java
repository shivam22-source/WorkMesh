package com.company.knowledge.orchestrator.ragclient;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Configuration for reaching rag-python. All values come from the environment
 * so no host or URL is baked into the build.
 */
@ConfigurationProperties(prefix = "rag")
public record RagClientProperties(
        String baseUrl,
        Duration connectTimeout,
        Duration readTimeout) {

    public RagClientProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            baseUrl = "http://localhost:8000";
        }
        if (connectTimeout == null) {
            connectTimeout = Duration.ofSeconds(2);
        }
        if (readTimeout == null) {
            readTimeout = Duration.ofSeconds(10);
        }
        baseUrl = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
    }
}
