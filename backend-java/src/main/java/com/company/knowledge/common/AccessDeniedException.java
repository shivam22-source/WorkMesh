package com.company.knowledge.common;

/**
 * Thrown when an authenticated identity lacks the required authorization or role.
 */
public class AccessDeniedException extends RuntimeException {

    public AccessDeniedException(String message) {
        super(message);
    }
}
