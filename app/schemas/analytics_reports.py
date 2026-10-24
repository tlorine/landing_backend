"""Publicly versioned response models: OpenAPI is the frontend contract source."""

from datetime import datetime

from pydantic import BaseModel, Field


class AuthResponse(BaseModel):
    username: str
    csrf_token: str


class CsrfResponse(BaseModel):
    csrf_token: str


class IngestionResponse(BaseModel):
    accepted: int
    duplicates: int
    ignored: int = 0


class Metric(BaseModel):
    value: int | None
    previous_value: int | None
    delta_abs: int | None
    delta_percent: float | None


class Summary(BaseModel):
    page_views: Metric
    sessions: Metric
    case_views: Metric
    outbound_clicks: Metric
    visitors: Metric | None = None


class Filters(BaseModel):
    source_site: str
    from_: str = Field(alias="from")
    to: str
    timezone: str
    locale: str | None
    country: str | None
    source_type: str | None
    source_value: str | None
    case_id: str | None


class Coverage(BaseModel):
    available_from: datetime | None
    session_available_from: datetime | None
    visitor_available_from: datetime | None = None
    partial: bool
    previous_partial: bool


class DailyPoint(BaseModel):
    date: str
    page_views: int
    sessions: int | None
    case_views: int
    outbound_clicks: int
    visitors: int | None = None


class ShareRow(BaseModel):
    key: str | None
    count: int
    share: float = Field(ge=0, le=1)
    visitor_count: int | None = None
    visitor_share: float | None = Field(default=None, ge=0, le=1)


class SourceRow(ShareRow):
    source_type: str


class CaseRow(BaseModel):
    id: str
    has_outbound_link: bool
    case_opens: int
    case_views: int
    case_view_sessions: int | None
    outbound_clicks: int
    outbound_sessions: int | None
    conversion: float | None = Field(ge=0, le=1)
    case_view_visitors: int | None = None
    outbound_visitors: int | None = None
    visitor_conversion: float | None = Field(default=None, ge=0, le=1)


class OverviewResponse(BaseModel):
    contract_version: str
    filters: Filters
    generated_at: datetime
    data_through: datetime
    coverage: Coverage
    warnings: list[str]
    summary: Summary
    daily_series: list[DailyPoint]
    countries: list[ShareRow]
    sources: list[SourceRow]
    devices: list[ShareRow]
    cases_preview: list[CaseRow]


class CasesResponse(BaseModel):
    contract_version: str
    filters: Filters
    generated_at: datetime
    data_through: datetime
    coverage: Coverage
    warnings: list[str]
    items: list[CaseRow]
    page: int
    page_size: int
    total: int


class Funnel(BaseModel):
    opens: int
    views: int
    outbound: int
    visitor_opens: int | None = None
    visitor_views: int | None = None
    visitor_outbound: int | None = None


class LinkRow(BaseModel):
    link_id: str
    count: int


class DetailResponse(OverviewResponse):
    case: CaseRow
    funnel: Funnel
    links: list[LinkRow]


class CoverageGap(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime | None


class SiteCapability(BaseModel):
    id: str
    coverage_start: datetime | None
    session_coverage_start: datetime | None
    gaps: list[CoverageGap]


class CaseCapability(BaseModel):
    id: str
    has_outbound_link: bool


class CapabilitiesResponse(BaseModel):
    contract_version: str
    manifest_version: str
    timezone: str
    max_days: int
    sites: list[SiteCapability]
    cases: list[CaseCapability]
    session_tracking_enabled: bool


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
