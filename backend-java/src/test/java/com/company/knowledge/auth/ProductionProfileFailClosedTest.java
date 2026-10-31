package com.company.knowledge.auth;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.knowledge.KnowledgeRagApplication;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.NoSuchBeanDefinitionException;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

class ProductionProfileFailClosedTest {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(KnowledgeRagApplication.class);

    @Test
    @DisplayName("No active profile loads DeterministicUserProvider successfully")
    void noActiveProfileLoadsDeterministicUserProvider() {
        contextRunner.run(context -> {
            assertThat(context).hasNotFailed();
            assertThat(context).hasSingleBean(CurrentUserProvider.class);
            assertThat(context.getBean(CurrentUserProvider.class))
                    .isInstanceOf(DeterministicUserProvider.class);
        });
    }

    @Test
    @DisplayName("dev profile loads DeterministicUserProvider successfully")
    void devProfileLoadsDeterministicUserProvider() {
        contextRunner
                .withPropertyValues("spring.profiles.active=dev")
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    assertThat(context).hasSingleBean(CurrentUserProvider.class);
                    assertThat(context.getBean(CurrentUserProvider.class))
                            .isInstanceOf(DeterministicUserProvider.class);
                });
    }

    @Test
    @DisplayName("prod profile fails startup closed without production CurrentUserProvider")
    void prodProfileFailsStartupClosedWithoutCurrentUserProvider() {
        contextRunner
                .withPropertyValues("spring.profiles.active=prod")
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure())
                            .hasRootCauseInstanceOf(NoSuchBeanDefinitionException.class)
                            .hasMessageContaining("CurrentUserProvider");
                });
    }

    @Test
    @DisplayName("dev and prod profiles combined fail startup closed without production CurrentUserProvider")
    void devAndProdProfilesCombinedFailsStartupClosed() {
        contextRunner
                .withPropertyValues("spring.profiles.active=dev,prod")
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure())
                            .hasRootCauseInstanceOf(NoSuchBeanDefinitionException.class)
                            .hasMessageContaining("CurrentUserProvider");
                });
    }
}
