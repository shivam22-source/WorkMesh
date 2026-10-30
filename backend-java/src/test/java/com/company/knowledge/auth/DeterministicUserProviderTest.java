package com.company.knowledge.auth;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

class DeterministicUserProviderTest {

    private final DeterministicUserProvider provider = new DeterministicUserProvider();

    @Test
    @DisplayName("defaults to employee_42 with engineering and backend groups")
    void defaultsToEmployee42() {
        RequestContextHolder.resetRequestAttributes();

        UserContext user = provider.getCurrentUser();

        assertThat(user.userId()).isEqualTo("employee_42");
        assertThat(user.email()).isEqualTo("employee_42@company.internal");
        assertThat(user.fullName()).isEqualTo("Alex Engineer");
        assertThat(user.role()).isEqualTo("ENGINEER");
        assertThat(user.groupIds()).containsExactlyInAnyOrder("group_engineering", "group_backend");
    }

    @Test
    @DisplayName("respects X-User-Id header for employee_admin")
    void respectsAdminHeader() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-User-Id", "employee_admin");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));

        try {
            UserContext user = provider.getCurrentUser();
            assertThat(user.userId()).isEqualTo("employee_admin");
            assertThat(user.role()).isEqualTo("ADMIN");
            assertThat(user.groupIds()).containsExactly("group_engineering");
        } finally {
            RequestContextHolder.resetRequestAttributes();
        }
    }

    @Test
    @DisplayName("respects X-User-Id header for custom user")
    void respectsCustomUserHeader() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader("X-User-Id", "employee_99");
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));

        try {
            UserContext user = provider.getCurrentUser();
            assertThat(user.userId()).isEqualTo("employee_99");
            assertThat(user.email()).isEqualTo("employee_99@company.internal");
        } finally {
            RequestContextHolder.resetRequestAttributes();
        }
    }
}
