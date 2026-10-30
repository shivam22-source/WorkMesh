package com.company.knowledge.search.dto;

import jakarta.validation.constraints.NotBlank;
import java.util.List;

/**
 * Request payload for POST /api/v1/ask.
 */
public record AskRequest(
        @NotBlank(message = "question must not be blank")
        String question,
        List<String> sourceTypes) {
}
