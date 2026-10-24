"""Typed period resolution and one consistent database snapshot per dashboard response."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.analytics_reports import AnalyticsReportsRepository
from app.schemas.analytics_reports import CapabilitiesResponse, DetailResponse, OverviewResponse
from app.services.analytics_manifest import CASES, MANIFEST
from app.services.periods import shift_months


@dataclass(frozen=True)
class ReportFilters:
    source_site: str
    start: date
    end: date
    timezone: str
    locale: str | None = None
    country: str | None = None
    source_type: str | None = None
    source_value: str | None = None
    case_id: str | None = None

    @classmethod
    def resolve(
        cls,
        source_site,
        start,
        end,
        timezone,
        locale=None,
        country=None,
        source_type=None,
        source_value=None,
        case_id=None,
    ):
        timezone = timezone or settings.stats_timezone
        try:
            zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Unknown timezone") from None
        today = datetime.now(UTC).astimezone(zone).date()
        end = end or today + timedelta(days=1)
        start = start or end - timedelta(days=30)
        if start > today:
            raise ValueError("Period cannot start in the future")
        if not 1 <= (end - start).days <= 366:
            raise ValueError("Period must contain 1–366 days")
        if source_site not in settings.analytics_sites:
            raise ValueError("Unknown source_site")
        if case_id and case_id not in CASES:
            raise ValueError("Unknown case_id")
        if locale not in (None, "ru", "en"):
            raise ValueError("Unknown locale")
        if country and country != "unknown" and (len(country) != 2 or not country.isalpha()):
            raise ValueError("Invalid country")
        if source_type not in (None, "utm", "referrer", "direct_unknown"):
            raise ValueError("Invalid source_type")
        if source_value and (not source_type or len(source_value) > 255):
            raise ValueError("source_value requires source_type and at most 255 characters")
        return cls(
            source_site,
            start,
            end,
            timezone,
            locale,
            country.upper() if country and country != "unknown" else country,
            source_type,
            source_value,
            case_id,
        )

    def bounds(self, previous: bool = False) -> tuple[datetime, datetime]:
        days = self.end - self.start
        start, end = (self.start - days, self.start) if previous else (self.start, self.end)
        zone = ZoneInfo(self.timezone)
        return (
            datetime.combine(start, time.min, zone).astimezone(UTC),
            datetime.combine(end, time.min, zone).astimezone(UTC),
        )

    def json(self) -> dict[str, str | None]:
        return {
            "source_site": self.source_site,
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "timezone": self.timezone,
            "locale": self.locale,
            "country": self.country,
            "source_type": self.source_type,
            "source_value": self.source_value,
            "case_id": self.case_id,
        }


class AnalyticsReportsService:
    def __init__(self) -> None:
        self.repository = AnalyticsReportsRepository()

    async def capabilities(self, session: AsyncSession) -> CapabilitiesResponse:
        intervals = await self.repository.coverage(session)
        sites = []
        for site in settings.analytics_sites:
            rows = [r for r in intervals if r.source_site == site]
            sites.append(
                {
                    "id": site,
                    "coverage_start": min((r.started_at for r in rows), default=None),
                    "session_coverage_start": min(
                        (r.started_at for r in rows if r.sessions_enabled), default=None
                    ),
                    "gaps": [
                        {"from": rows[i].ended_at, "to": rows[i + 1].started_at}
                        for i in range(len(rows) - 1)
                        if rows[i].ended_at
                    ],
                }
            )
        return CapabilitiesResponse.model_validate(
            {
                "contract_version": "1",
                "manifest_version": MANIFEST["version"],
                "timezone": settings.stats_timezone,
                "max_days": 366,
                "sites": sites,
                "cases": list(CASES.values()),
                "session_tracking_enabled": settings.analytics_sessions_enabled,
            }
        )

    async def report(
        self, session: AsyncSession, filters: ReportFilters, detail: bool = False
    ) -> OverviewResponse | DetailResponse:
        async with session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            now = (await session.execute(text("SELECT transaction_timestamp()"))).scalar_one()
            coverage_rows = await self.repository.coverage(session, filters.source_site)
            retention = datetime.combine(
                shift_months(now.date(), -settings.analytics_retention_months), time.min, UTC
            )
            first = min((r.started_at for r in coverage_rows), default=None)
            session_first = min(
                (r.started_at for r in coverage_rows if r.sessions_enabled), default=None
            )
            available = max(first, retention) if first else None
            session_available = max(session_first, retention) if session_first else None
            start, end = filters.bounds()
            pstart, pend = filters.bounds(previous=True)

            def covered(left, right, sessions=False):
                # Treat the live part of today as partial, but do not demand future coverage.
                right = min(right, now)
                cursor = left
                for row in coverage_rows:
                    if sessions and not row.sessions_enabled:
                        continue
                    if row.started_at > cursor:
                        continue
                    finish = row.ended_at or now
                    if finish > cursor:
                        cursor = finish
                    if cursor >= right:
                        return left >= retention
                return False

            partial = not covered(start, end)
            previous_partial = not covered(pstart, pend)
            session_partial = not covered(start, end, sessions=True)
            previous_session_partial = not covered(pstart, pend, sessions=True)
            sessions = session_available is not None and any(
                row.sessions_enabled
                and row.started_at < min(end, now)
                and (row.ended_at or now) > start
                for row in coverage_rows
            )
            current = await self.repository.totals(session, filters, start, end, sessions)
            previous = await self.repository.totals(session, filters, pstart, pend, sessions)
            summary = {}
            for key, value in current.items():
                old = (
                    None
                    if previous_partial
                    or (key == "sessions" and (session_partial or previous_session_partial))
                    else previous[key]
                )
                delta = value - old if value is not None and old is not None else None
                summary[key] = {
                    "value": value,
                    "previous_value": old,
                    "delta_abs": delta,
                    "delta_percent": delta / old if old and delta is not None else None,
                }
            daily = await self.repository.daily(session, filters, start, end, sessions)
            indexed = {row["date"]: row for row in daily}
            series = []
            day = filters.start
            while day < filters.end:
                series.append(
                    indexed.get(
                        day.isoformat(),
                        {
                            "date": day.isoformat(),
                            "page_views": 0,
                            "sessions": 0 if sessions else None,
                            "case_views": 0,
                            "outbound_clicks": 0,
                        },
                    )
                )
                day += timedelta(days=1)
            countries = (
                await self.repository.breakdown(session, filters, start, end, "country")
                if sessions
                else []
            )
            sources = (
                await self.repository.breakdown(session, filters, start, end, "source")
                if sessions
                else []
            )
            cases = await self.repository.cases(session, filters, start, end, sessions)
            warnings = []
            if not settings.trust_cloudflare_headers or not settings.trusted_proxy_cidrs:
                warnings.append(
                    "Доверенный proxy для геоданных не настроен; страны могут быть неизвестны."
                )
            if partial:
                warnings.append("Период содержит неполное покрытие аналитикой.")
            if previous_partial:
                warnings.append("Предыдущий период покрыт не полностью; сравнение недоступно.")
            if sessions and session_partial:
                warnings.append("Сессионные данные покрывают период не полностью.")
            if not sessions:
                warnings.append("Сессионные метрики пока недоступны.")
            if end > now:
                warnings.append("Текущий день неполный.")
            payload = {
                "contract_version": "1",
                "filters": filters.json(),
                "generated_at": now,
                "data_through": now,
                "coverage": {
                    "available_from": available,
                    "session_available_from": session_available,
                    "partial": partial,
                    "previous_partial": previous_partial,
                },
                "warnings": warnings,
                "summary": summary,
                "daily_series": series,
                "countries": countries,
                "sources": sources,
                "cases_preview": cases,
            }
            if detail:
                payload["case"] = next(row for row in cases if row["id"] == filters.case_id)
                payload["funnel"] = await self.repository.funnel(session, filters, start, end)
                payload["links"] = await self.repository.links(session, filters, start, end)
            return (
                DetailResponse.model_validate(payload)
                if detail
                else OverviewResponse.model_validate(payload)
            )
