"""Application settings for rag-python.

Every value is environment-driven so nothing host-specific is committed.
"""

from functools import lru_cache

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

    # Phase 0 only. Postgres connection settings arrive in Phase 1 together
    # with the schema, so they are deliberately absent here.
    contract_version: str = "v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()