from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    # Server-side output ceiling to bound worst-case provider usage per request.
    ai_max_output_tokens: int = Field(default=2048, ge=256, le=8192)
    openai_api_key: str | None = None
    deepseek_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_api_base: str = "http://localhost:11434"

    # Supabase Auth verifies user sessions. Never put the service-role key in the frontend.
    supabase_url: str | None = None
    # Server-only key; never expose to frontend or API responses.
    supabase_service_role_key: str | None = None
    # Prefer immutable Supabase auth user UUID for production admin assignment.
    owner_user_id: str | None = None
    # Transitional fallback for deployments that have not configured owner_user_id.
    owner_email: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
