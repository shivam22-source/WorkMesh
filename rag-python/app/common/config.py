"""Application settings for rag-python.

Every value is environment-driven so nothing host-specific is committed.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    auth_mode: str = "prod"  # "prod" or "dev"
    jwt_secret: str = "workmesh_jwt_secret_dev_key_only_change_in_prod"
    jwt_algorithm: str = "HS256"

    # PostgreSQL / pgvector settings
    postgres_host: str = "172.19.63.124"
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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
