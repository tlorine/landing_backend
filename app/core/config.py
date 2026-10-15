from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
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

    stats_timezone: str = "Europe/Moscow"
    visits_retention_months: int = Field(default=12, ge=1, le=36)
    visits_rate_limit_per_minute: int = Field(default=30, ge=1, le=600)
    telegram_commands_enabled: bool = True
    telegram_poll_timeout_seconds: int = Field(default=25, ge=1, le=50)

    @field_validator("stats_timezone")
    @classmethod
    def validate_stats_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown time zone {value!r} in STATS_TIMEZONE.") from exc
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        # The browser sends Origin without a trailing slash; a mismatch silently blocks requests.
        normalized = [origin.strip().rstrip("/") for origin in origins]
        for origin in normalized:
            if origin == "*":
                raise ValueError("CORS_ORIGINS must list exact origins; '*' is not allowed.")
            scheme, sep, host = origin.partition("://")
            if scheme not in ("http", "https") or not sep or not host or "/" in host:
                raise ValueError(
                    f"Invalid CORS origin {origin!r}: expected scheme://host[:port] without a path."
                )
        return normalized

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

    @property
    def stats_zone(self) -> ZoneInfo:
        return ZoneInfo(self.stats_timezone)


settings = Settings()
