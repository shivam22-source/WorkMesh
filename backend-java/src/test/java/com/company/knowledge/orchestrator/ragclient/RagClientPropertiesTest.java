package com.company.knowledge.orchestrator.ragclient;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Guards the defaults and the trailing-slash normalisation, because a
 * double slash in the base URL produces a 404 from FastAPI that looks like a
 * service outage.
 */
class RagClientPropertiesTest {

    @Test
    @DisplayName("blank base url falls back to the local RAG service")
    void blankBaseUrlFallsBack() {
        RagClientProperties properties = new RagClientProperties("  ", null, null);

        assertThat(properties.baseUrl()).isEqualTo("http://localhost:8000");
        assertThat(properties.connectTimeout()).isNotNull();
        assertThat(properties.readTimeout()).isNotNull();
    }

    @Test
    @DisplayName("trailing slash is removed so URIs do not double up")
    void trailingSlashIsRemoved() {
        RagClientProperties properties =
                new RagClientProperties("http://rag-python:8000/", null, null);

        assertThat(properties.baseUrl()).isEqualTo("http://rag-python:8000");
    }
}
