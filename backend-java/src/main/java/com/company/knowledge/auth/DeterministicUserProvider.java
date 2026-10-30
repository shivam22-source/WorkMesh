package com.company.knowledge.auth;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/**
 * Deterministic local authentication provider for development and testing.
 *
 * <p>Always provides employee_42 (Alex Engineer, Engineering & Backend groups)
 * unless an optional X-User-Id header is passed to simulate another identity
 * (e.g. employee_admin or a custom test user).
 */
@Component
public class DeterministicUserProvider implements CurrentUserProvider {

    public static final String DEFAULT_USER_ID = "employee_42";
    public static final String DEFAULT_EMAIL = "employee_42@company.internal";
    public static final String DEFAULT_NAME = "Alex Engineer";
    public static final String DEFAULT_ROLE = "ENGINEER";
    public static final Set<String> DEFAULT_GROUPS = Set.of("group_engineering", "group_backend");

    @Override
    public UserContext getCurrentUser() {
        ServletRequestAttributes attributes =
                (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();

        if (attributes != null) {
            HttpServletRequest request = attributes.getRequest();
            String headerUserId = request.getHeader("X-User-Id");
            if (headerUserId != null && !headerUserId.isBlank()) {
                String cleanId = headerUserId.trim();
                if ("employee_admin".equalsIgnoreCase(cleanId)) {
                    return new UserContext(
                            "employee_admin",
                            "admin@company.internal",
                            "Sam Admin",
                            "ADMIN",
                            Set.of("group_engineering"));
                }
                return new UserContext(
                        cleanId,
                        cleanId + "@company.internal",
                        "Test User (" + cleanId + ")",
                        DEFAULT_ROLE,
                        DEFAULT_GROUPS);
            }
        }

        return new UserContext(
                DEFAULT_USER_ID,
                DEFAULT_EMAIL,
                DEFAULT_NAME,
                DEFAULT_ROLE,
                DEFAULT_GROUPS);
    }
}
