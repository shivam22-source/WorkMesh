package com.company.knowledge;

import com.company.knowledge.orchestrator.ragclient.RagClientProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * Entry point for backend-java.
 *
 * <p>backend-java owns authentication and user context, permission decisions,
 * REST APIs, orchestration, audit/admin endpoints, and all calls into the
 * Python RAG service. It deliberately owns no retrieval logic.
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class KnowledgeRagApplication {

    public static void main(String[] args) {
        SpringApplication.run(KnowledgeRagApplication.class, args);
    }
}
