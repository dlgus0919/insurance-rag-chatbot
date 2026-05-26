"""Typed API settings loaded from environment variables."""

from __future__ import annotations

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - dependency is declared for API runtime.
    from pydantic import BaseModel as BaseSettings

    SettingsConfigDict = dict


class ApiSettings(BaseSettings):
    """FastAPI runtime settings."""

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080,http://localhost:8501"
    cookie_secure: bool = True
    jwt_secret: str = "dev-only-change-me"
    access_token_seconds: int = 15 * 60
    refresh_token_seconds: int = 7 * 24 * 60 * 60
    database_url: str = "sqlite+aiosqlite:///./insurance_chat.db"

    model_config = SettingsConfigDict(env_prefix="API_", env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def get_api_settings() -> ApiSettings:
    """Load API settings from .env and process environment."""

    return ApiSettings()
