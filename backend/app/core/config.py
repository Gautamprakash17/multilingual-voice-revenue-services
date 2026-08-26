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

    # POC officer RBAC token (header X-Officer-Token). Not a production secret store.
    officer_api_token: str = Field(
        default="officer-poc-token",
        description="Shared token for officer dashboard APIs",
    )

    # CORS
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:5174,http://localhost:3000",
        description="Comma-separated allowed origins",
    )

    # Logging
    log_level: str = "INFO"

    # Local mock OTP (not a real SMS provider)
    otp_ttl_seconds: int = Field(default=300, description="OTP challenge lifetime in seconds")
    otp_max_attempts: int = Field(default=3, description="Failed OTP attempts before reissue")

    # Local STT (faster-whisper). "tiny" is multilingual but has poor accuracy
    # on Hindi/Kannada; "small" is the practical floor for usable Indic-language
    # recognition on CPU. Override with WHISPER_MODEL_SIZE if you have GPU/more
    # CPU headroom (e.g. "medium") or need faster/lower-memory ("base").
    whisper_model_size: str = Field(
        default="small",
        description="faster-whisper model size: tiny|base|small|medium|large-v3",
    )
    whisper_beam_size: int = Field(
        default=5, description="Beam search width; higher = more accurate, slower"
    )

    # Local TTS: Piper neural voices for English/Hindi; eSpeak NG fallback (incl. Kannada).
    piper_bin: str = Field(default="piper", description="Piper TTS binary path or name")
    tts_voices_dir: str = Field(
        default="data/tts",
        description="Directory containing Piper ONNX voice files",
    )
    piper_en_voice: str = Field(
        default="en_US-lessac-medium.onnx",
        description="Piper English voice filename under tts_voices_dir",
    )
    piper_hi_voice: str = Field(
        default="hi_IN-priyamvada-medium.onnx",
        description="Piper Hindi (Indic) voice filename under tts_voices_dir",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
