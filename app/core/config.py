from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Landing Requests API"
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+asyncpg://app:change-me@localhost:5432/requests_db"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:3001"]
    )
    log_level: str = "INFO"
    sql_echo: bool = False

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    notification_poll_interval_seconds: float = Field(default=3.0, ge=1.0, le=60.0)
    notification_retry_max_seconds: int = Field(default=3600, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_telegram_credentials(self) -> Settings:
        has_token = bool(self.telegram_bot_token)
        has_chat_id = bool(self.telegram_chat_id)
        if has_token != has_chat_id:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must either both be set or both be empty."
            )
        return self

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


settings = Settings()
