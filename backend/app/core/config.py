"""Application settings — environment-based, no secrets in source."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment / .env files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Multilingual Voice-First Revenue Services Platform"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = Field(
        default="postgresql+psycopg2://revenue:revenue@localhost:5432/revenue_poc",
        description="SQLAlchemy database URL",
    )

    # Provider mode: local (default) or cloud (gated by boundary gateway)
    provider_mode: Literal["local", "cloud"] = "local"
    cloud_ai_enabled: bool = False

    # Boundary policy file (relative to repo root or absolute)
    boundary_policy_path: str = "config/boundary/policies.yaml"

    # Local document storage (RESTRICTED) — never cloud
    document_storage_path: str = Field(
        default="data/documents",
        description="Local filesystem directory for uploaded documents",
    )

    # CORS
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:5174,http://localhost:3000",
        description="Comma-separated allowed origins",
    )

    # Logging
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
