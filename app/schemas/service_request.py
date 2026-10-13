from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator

_TELEGRAM_USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{4,31}$")
_PHONE_RE = re.compile(r"^\+?[0-9\s().-]+$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ServiceRequestCreate(BaseModel):
    """Validated public payload accepted from a landing page."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, max_length=100, description="Имя, необязательно")
    budget: str | None = Field(default=None, max_length=100, description="Бюджет, необязательно")
    contact: str = Field(min_length=5, max_length=254, description="Email, телефон или @Telegram")
    description: str = Field(min_length=10, max_length=5000)
    source_site: str = Field(
        min_length=1,
        max_length=255,
        description="Домен или идентификатор сайта",
    )

    @field_validator("name", "budget", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("contact")
    @classmethod
    def validate_contact(cls, value: str) -> str:
        if _TELEGRAM_USERNAME_RE.fullmatch(value):
            return value

        if "@" in value:
            try:
                validate_email(value, check_deliverability=False)
                return value
            except EmailNotValidError:
                pass

        if _PHONE_RE.fullmatch(value):
            digits = re.sub(r"\D", "", value)
            if 7 <= len(digits) <= 15:
                return value

        raise ValueError("Укажите email, телефон или Telegram в формате @username.")

    @field_validator("name", "budget", "contact", "description", "source_site")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL_CHARS_RE.search(value):
            raise ValueError("Текст содержит недопустимые управляющие символы.")
        return value


class ServiceRequestCreated(BaseModel):
    id: UUID
    status: Literal["accepted"] = "accepted"
    created_at: datetime
