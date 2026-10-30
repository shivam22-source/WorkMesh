package com.company.knowledge.auth;

import java.util.Set;

/**
 * Immutable user context representing the authenticated employee making a request.
 *
 * <p>In Phase 1, this is deterministically populated by {@link CurrentUserProvider}.
 * In Phase 4, the groupIds are evaluated against ACL references in retrieval queries.
 */
public record UserContext(
        String userId,
        String email,
        String fullName,
        String role,
        Set<String> groupIds) {
}
