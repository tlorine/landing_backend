from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.service_requests import ServiceRequestRepository
from app.repositories.site_visits import SiteVisitRepository, UtmCampaignRow
from app.services.periods import Period, ResolvedPeriod, resolve_period


@dataclass(frozen=True, slots=True)
class ShareRow:
    """One line of a breakdown. ``key`` None means "unknown" (or direct visits for referrers)."""

    key: str | None
    visits: int
    percent: int
    is_other: bool = False


@dataclass(frozen=True, slots=True)
class VisitorsReport:
    period: ResolvedPeriod
    visits: int
    visitors: int
    requests: int
    conversion: float | None
    countries: list[ShareRow]
    devices: list[ShareRow]
    os: list[ShareRow]
    browsers: list[ShareRow]
    locales: list[ShareRow]
    sites: list[ShareRow]


@dataclass(frozen=True, slots=True)
class SourcesReport:
    period: ResolvedPeriod
    visits: int
    referrers: list[ShareRow]
    utm_campaigns: list[UtmCampaignRow]


_REFERRER_GROUPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(t\.me|telegram\.me|telegram\.org|web\.telegram\.org)$"), "Telegram"),
    (re.compile(r"^google\.[a-z.]+$"), "Google"),
    (re.compile(r"^(yandex\.[a-z.]+|ya\.ru)$"), "Яндекс"),
    (re.compile(r"^(m\.)?vk\.com$"), "VK"),
)


def referrer_group(host: str | None) -> str | None:
    if host is None:
        return None
    for pattern, name in _REFERRER_GROUPS:
        if pattern.fullmatch(host):
            return name
    return host


def percent(part: int, total: int) -> int:
    """Whole percent rounded half up; shares may not sum to exactly 100."""
    if total <= 0:
        return 0
    return (200 * part + total) // (2 * total)


def share_rows(
    counts: list[tuple[str | None, int]],
    total: int,
    top: int | None = None,
    unknown_last: bool = False,
) -> list[ShareRow]:
    """Sorted rows, the rest folded into "other"; optionally the None row kept apart at the end."""
    unknown = [count for key, count in counts if key is None] if unknown_last else []
    known = [(key, count) for key, count in counts if not (unknown_last and key is None)]
    known.sort(key=lambda item: (-item[1], item[0] is None, item[0] or ""))
    shown = known if top is None else known[:top]
    rest = sum(count for _, count in known[len(shown) :])

    rows = [ShareRow(key, count, percent(count, total)) for key, count in shown]
    if rest:
        rows.append(ShareRow(None, rest, percent(rest, total), is_other=True))
    if unknown and unknown[0]:
        rows.append(ShareRow(None, unknown[0], percent(unknown[0], total)))
    return rows


class VisitStatsService:
    """Typed visit statistics for a calendar period; knows nothing about Telegram."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        visit_repository: SiteVisitRepository,
        request_repository: ServiceRequestRepository,
        tz: ZoneInfo,
    ) -> None:
        self._session_factory = session_factory
        self._visits = visit_repository
        self._requests = request_repository
        self._tz = tz

    async def visitors_report(self, period: Period, now: datetime) -> VisitorsReport:
        resolved = resolve_period(period, now, self._tz)
        start, end = resolved.start_utc, resolved.end_utc
        async with self._session_factory() as session:
            totals = await self._visits.totals(session, start, end)
            requests = await self._requests.count_created_between(session, start, end)
            breakdowns = {
                column: await self._visits.breakdown(session, column, start, end)
                for column in ("country", "device_type", "os", "browser", "locale")
            }
            sites = await self._visits.sites(session, start, end)

        visits = totals.visits
        return VisitorsReport(
            period=resolved,
            visits=visits,
            visitors=totals.visitors,
            requests=requests,
            conversion=requests / totals.visitors if totals.visitors else None,
            countries=share_rows(breakdowns["country"], visits, top=10, unknown_last=True),
            devices=share_rows(breakdowns["device_type"], visits),
            os=share_rows(breakdowns["os"], visits, top=5),
            browsers=share_rows(breakdowns["browser"], visits, top=5),
            locales=share_rows(breakdowns["locale"], visits),
            sites=share_rows([(site, count) for site, count in sites], visits),
        )

    async def sources_report(self, period: Period, now: datetime) -> SourcesReport:
        resolved = resolve_period(period, now, self._tz)
        start, end = resolved.start_utc, resolved.end_utc
        async with self._session_factory() as session:
            totals = await self._visits.totals(session, start, end)
            hosts = await self._visits.breakdown(session, "referrer_host", start, end)
            campaigns = await self._visits.utm_campaigns(session, start, end, limit=10)

        grouped: dict[str | None, int] = {}
        for host, count in hosts:
            group = referrer_group(host)
            grouped[group] = grouped.get(group, 0) + count
        return SourcesReport(
            period=resolved,
            visits=totals.visits,
            referrers=share_rows(list(grouped.items()), totals.visits, top=10),
            utm_campaigns=campaigns,
        )
