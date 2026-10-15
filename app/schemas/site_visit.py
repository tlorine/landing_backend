from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.service_request import _CONTROL_CHARS_RE

_REFERRER_HOST_RE = re.compile(r"^[a-z0-9.-]{1,255}$")


class VisitCreate(BaseModel):
    """Anonymous page-load beacon sent by a landing page."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    source_site: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=512)
    locale: Literal["ru", "en"] | None = None
    device_type: Literal["mobile", "tablet", "desktop"] | None = None
    referrer_host: str | None = None
    utm_source: str | None = Field(default=None, max_length=100)
    utm_medium: str | None = Field(default=None, max_length=100)
    utm_campaign: str | None = Field(default=None, max_length=100)

    @field_validator("path", mode="before")
    @classmethod
    def strip_query_and_fragment(cls, value: object) -> object:
        if isinstance(value, str):
            return re.split(r"[?#]", value.strip(), maxsplit=1)[0]
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("Путь должен начинаться с /.")
        return value

    @field_validator("referrer_host", mode="before")
    @classmethod
    def normalize_referrer_host(cls, value: object) -> str | None:
        # Referrer data is best-effort: anything unexpected is treated as unknown, not an error.
        if not isinstance(value, str):
            return None
        host = value.strip().lower().removeprefix("www.")
        return host if _REFERRER_HOST_RE.fullmatch(host) else None

    @field_validator("utm_source", "utm_medium", "utm_campaign", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("source_site", "path", "utm_source", "utm_medium", "utm_campaign")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL_CHARS_RE.search(value):
            raise ValueError("Текст содержит недопустимые управляющие символы.")
        return value
