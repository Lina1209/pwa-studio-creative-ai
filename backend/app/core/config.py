from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PWA Studio API"
    app_env: Literal["development", "production", "test"] = "development"
    api_prefix: str = "/api"
    cors_origins: str = (
        "http://localhost:5500,http://127.0.0.1:5500,"
        "https://lina1209.github.io"
    )

    ai_provider: str = "deepseek"
    ai_model: str = "deepseek-flash"
    ai_max_concurrent_requests: int = Field(default=4, ge=1, le=32)
    ai_queue_wait_seconds: float = Field(default=10.0, ge=0.0, le=60.0)
    ai_request_timeout_seconds: int = Field(default=90, ge=5, le=300)
    ai_max_retries: int = Field(default=1, ge=0, le=3)
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_api_base: str = "http://localhost:11434"

    # Supabase Auth verifies user sessions. Never put the service-role key in the frontend.
    supabase_url: str | None = None
    # Server-only key; never expose to frontend or API responses.
    supabase_service_role_key: str | None = None
    # Keep job endpoints disabled until migrations 0009/0010 and the worker path are reviewed.
    generation_jobs_enabled: bool = False
    # HMAC secret for short-lived, owner-bound server pricing quotes (>=32 bytes).
    pricing_quote_signing_secret: str | None = None
    # Keep submission disabled until a durable dispatcher and worker are deployed.
    generation_job_worker_ready: bool = False
    # Runtime remains off until real provider and private storage adapters are deployed.
    generation_worker_runtime_enabled: bool = False
    generation_worker_idle_poll_seconds: float = Field(default=3.0, ge=0.25, le=60.0)
    generation_worker_error_backoff_seconds: float = Field(default=5.0, ge=0.25, le=300.0)
    generation_storage_bucket: str = "studio-media"
    generation_storage_timeout_seconds: float = Field(default=30.0, ge=1.0, le=180.0)
    image_generation_provider: str | None = None
    image_generation_model: str | None = None
    owner_email: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("generation_storage_bucket")
    @classmethod
    def validate_generation_storage_bucket(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 100
            or "/" in value
            or "\\\\" in value
            or value.strip() != value
        ):
            raise ValueError("Generation storage bucket name is invalid.")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
