from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PWA Studio API"
    app_env: Literal["development", "production", "test"] = "development"
    api_prefix: str = "/api"
    cors_origins: str = (
        "http://localhost:5500,http://127.0.0.1:5500,"
        "https://lina1209.github.io"
    )

    # Only DeepSeek and Google Gemini are supported. DeepSeek remains the default.
    ai_provider: Literal["deepseek", "gemini"] = "deepseek"
    ai_model: str = "deepseek-flash"
    ai_max_concurrent_requests: int = Field(default=4, ge=1, le=32)
    ai_queue_wait_seconds: float = Field(default=10.0, ge=0.0, le=60.0)
    ai_request_timeout_seconds: int = Field(default=90, ge=5, le=300)
    ai_max_retries: int = Field(default=1, ge=0, le=3)
    ai_max_output_tokens: int = Field(default=2048, ge=1, le=8192)
    ai_max_requests_per_minute_per_user: int = Field(default=10, ge=1, le=120)
    ai_max_requests_per_day_per_user: int = Field(default=100, ge=1, le=10000)
    ai_max_requests_per_day_global: int = Field(default=2000, ge=1, le=100000)
    ai_max_concurrent_requests_per_user: int = Field(default=2, ge=1, le=16)
    ai_max_global_concurrent_requests: int = Field(default=16, ge=1, le=128)
    deepseek_api_key: str | None = None
    gemini_api_key: str | None = None

    # Supabase Auth verifies user sessions. Never put the service-role key in the frontend.
    supabase_url: str | None = None
    # Server-only key; never expose to frontend or API responses.
    supabase_service_role_key: str | None = None
    # Comma-separated immutable Supabase Auth user UUIDs allowed to administer the app.
    # Empty means no administrator is configured; email addresses are never authorization identities.
    owner_user_ids: str | None = None
    # Keep job endpoints disabled until migrations 0009/0010 and the worker path are reviewed.
    generation_jobs_enabled: bool = False
    # HMAC secret for short-lived, owner-bound server pricing quotes (>=32 bytes).
    pricing_quote_signing_secret: str | None = None
    # Empty catalog means pricing is unavailable; configure only approved server-side rules.
    pricing_catalog_json: str = '{"version":"unconfigured","rules":[]}'
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_ai_provider_model(self):
        allowed_models = {
            "deepseek": {"deepseek-flash", "deepseek-v4-pro"},
            "gemini": {"gemini-3.1-flash-lite"},
        }
        if self.ai_model not in allowed_models[self.ai_provider]:
            raise ValueError("AI_MODEL is not allowed for the selected AI_PROVIDER.")
        return self

    @field_validator("generation_storage_bucket")
    @classmethod
    def validate_generation_storage_bucket(cls, value: str) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 100
            or "/" in value
            or "\\" in value
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
