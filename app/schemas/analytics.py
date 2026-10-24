from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.site_visit import VisitCreate


class EntryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    entry_page_view_id: UUID
    started_at: datetime
    path: str = Field(max_length=512)
    referrer_host: str | None = Field(default=None, max_length=255)
    utm_source: str | None = Field(default=None, max_length=100)
    utm_medium: str | None = Field(default=None, max_length=100)
    utm_campaign: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def clean_context(self):
        clean = VisitCreate(
            source_site="context",
            path=self.path,
            referrer_host=self.referrer_host,
            utm_source=self.utm_source,
            utm_medium=self.utm_medium,
            utm_campaign=self.utm_campaign,
        )
        if clean.path != self.path or not self.path.startswith("/"):
            raise ValueError("entry path must not contain query or fragment")
        self.referrer_host = clean.referrer_host
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must have timezone")
        self.started_at = self.started_at.astimezone(UTC)
        return self


class AnalyticsEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    event_id: UUID
    event_type: Literal["page_view", "case_open", "case_outbound_click"]
    occurred_at: datetime
    source_site: str = Field(min_length=1, max_length=255)
    session_id: UUID | None = None
    page_view_id: UUID
    navigation_id: UUID | None = None
    sequence: int = Field(ge=1, le=1000000)
    path: str = Field(max_length=512)
    locale: Literal["ru", "en"]
    device_type: Literal["mobile", "tablet", "desktop"]
    case_id: str | None = Field(default=None, max_length=100)
    link_id: str | None = Field(default=None, max_length=100)
    placement: Literal["home_cases", "case_project"] | None = None
    entry_context: EntryContext | None = None

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("occurred_at must have timezone")
        return value.astimezone(UTC)


class AnalyticsBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    events: list[AnalyticsEventCreate] = Field(min_length=1, max_length=20)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=1024)
