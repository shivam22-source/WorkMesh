"""Application settings for rag-python.

Every value is environment-driven so nothing host-specific is committed.
"""

from functools import lru_cache
import logging
from typing import List, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_JWT_SECRET = "workmesh_jwt_secret_dev_key_only_change_in_prod"
KNOWN_DEFAULT_JWT_SECRETS = {
    DEFAULT_DEV_JWT_SECRET,
    "replace_with_a_secure_random_key_of_at_least_32_characters_for_prod",
    "changeme",
    "secret",
}


class Settings(BaseSettings):
    """Runtime configuration, read from the environment or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "rag-python"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    contract_version: str = "v1"

    # Auth settings
    auth_mode: str = "prod"  # strictly "prod" or "dev"
    jwt_secret: Optional[str] = None
    jwt_algorithm: str = "HS256"
    jwt_algorithms: Optional[str] = None  # optional comma-separated explicit allowlist
    jwt_max_ttl_seconds: int = 86400

    @property
    def allowed_jwt_algorithms(self) -> List[str]:
        raw = self.jwt_algorithms or self.jwt_algorithm
        return [a.strip() for a in raw.split(",") if a.strip()]

    @property
    def is_prod(self) -> bool:
        return self.auth_mode == "prod"

    @property
    def is_dev(self) -> bool:
        return self.auth_mode == "dev"

    @model_validator(mode="after")
    def validate_auth_settings(self) -> "Settings":
        raw_mode = (self.auth_mode or "").strip().lower()
        if raw_mode not in ("prod", "dev"):
            raise ValueError(
                f"Invalid AUTH_MODE '{self.auth_mode}'. Must be strictly 'prod' or 'dev'."
            )
        self.auth_mode = raw_mode

        if self.jwt_max_ttl_seconds <= 0:
            raise ValueError("JWT_MAX_TTL_SECONDS must be a positive integer")

        algos = self.allowed_jwt_algorithms
        if not algos or any(a.lower() == "none" for a in algos):
            raise ValueError(
                "Invalid JWT algorithm configuration: empty list or 'none' algorithm is forbidden."
            )

        if self.is_dev:
            if not self.jwt_secret:
                self.jwt_secret = DEFAULT_DEV_JWT_SECRET
            if self.jwt_secret == DEFAULT_DEV_JWT_SECRET:
                logging.getLogger(__name__).warning(
                    "SECURITY WARNING: Using default JWT secret in dev mode. Set a strong JWT_SECRET before deploying to production."
                )
        else:
            # Production mode validation
            if not self.jwt_secret:
                raise ValueError(
                    "JWT_SECRET is required in production mode (AUTH_MODE=prod). App startup aborted."
                )
            if self.jwt_secret in KNOWN_DEFAULT_JWT_SECRETS:
                raise ValueError(
                    "JWT_SECRET cannot use the known dev default in production mode. App startup aborted."
                )
            if len(self.jwt_secret) < 32:
                raise ValueError(
                    f"JWT_SECRET is too short ({len(self.jwt_secret)} characters). Must be at least 32 characters in production mode. App startup aborted."
                )
        return self

    # PostgreSQL / pgvector settings
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "knowledge"
    postgres_user: str = "knowledge"
    postgres_password: str = "local_dev_only_change_me"

    # Embedding settings
    embedding_provider: str = "sentence-transformers"  # local sentence-transformers only
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    openai_api_key: Optional[str] = None

    # Source connectors
    github_token: Optional[str] = None
    github_repo: Optional[str] = None

    # Backpressure & concurrency limits
    search_concurrency_limit: int = 15
    search_retry_after_seconds: int = 1

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
