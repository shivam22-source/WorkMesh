package com.company.knowledge.search.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import java.util.List;

/**
 * Request payload for POST /api/v1/search.
 */
public record SearchRequest(
        @NotBlank(message = "query must not be blank")
        String query,
        @Min(value = 1, message = "limit must be at least 1")
        @Max(value = 50, message = "limit must not exceed 50")
        Integer limit,
        List<String> sourceTypes) {

    public int resolvedLimit() {
        return (limit != null && limit > 0) ? limit : 10;
    }
}
