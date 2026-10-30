package com.company.knowledge.auth;

/**
 * Strategy interface to resolve the current user context for the active request.
 */
public interface CurrentUserProvider {

    /**
     * Resolve the current user context.
     *
     * @return current UserContext
     */
    UserContext getCurrentUser();
}
