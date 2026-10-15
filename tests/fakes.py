"""In-memory stand-ins for the database layer; CI has no PostgreSQL."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.models.site_visit import SiteVisit
from app.repositories.site_visits import BREAKDOWN_COLUMNS, UtmCampaignRow, VisitTotals


class FakeSession:
    @asynccontextmanager
    async def begin(self) -> Any:
        yield self


class FakeSessionFactory:
    def __call__(self) -> Any:
        @asynccontextmanager
        async def session() -> Any:
            yield FakeSession()

        return session()


@dataclass
class StoredVisit:
    occurred_at: datetime
    source_site: str = "studio-landing"
    country: str | None = None
    device_type: str = "desktop"
    os: str = "Windows"
    browser: str = "Chrome"
    locale: str | None = "ru"
    referrer_host: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    visitor_hash: str = "0" * 64


def _group(counts: dict[Any, int]) -> list[tuple[Any, int]]:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0] is None, str(item[0])))


class FakeSiteVisitRepository:
    def __init__(self, visits: list[StoredVisit] | None = None) -> None:
        self.visits = list(visits or [])
        self.added: list[SiteVisit] = []
        self.salts: dict[date, bytes] = {}
        self.salt_calls = 0

    async def add(self, session: Any, visit: SiteVisit) -> None:
        self.added.append(visit)

    async def get_or_create_salt(self, session: Any, day: date) -> bytes:
        self.salt_calls += 1
        return self.salts.setdefault(day, bytes([len(self.salts)]) * 32)

    def _window(self, start: datetime, end: datetime) -> list[StoredVisit]:
        return [visit for visit in self.visits if start <= visit.occurred_at < end]

    async def totals(self, session: Any, start: datetime, end: datetime, source_site=None):
        rows = self._window(start, end)
        return VisitTotals(len(rows), len({row.visitor_hash for row in rows}))

    async def breakdown(self, session: Any, column, start, end, limit=None, source_site=None):
        assert column in BREAKDOWN_COLUMNS
        counts: dict[Any, int] = {}
        for row in self._window(start, end):
            key = getattr(row, column)
            counts[key] = counts.get(key, 0) + 1
        return _group(counts)[:limit]

    async def utm_campaigns(self, session: Any, start, end, limit, source_site=None):
        counts: dict[Any, int] = {}
        for row in self._window(start, end):
            key = (row.utm_source, row.utm_medium, row.utm_campaign)
            if any(key):
                counts[key] = counts.get(key, 0) + 1
        return [UtmCampaignRow(*key, visits) for key, visits in _group(counts)[:limit]]

    async def sites(self, session: Any, start, end):
        counts: dict[Any, int] = {}
        for row in self._window(start, end):
            counts[row.source_site] = counts.get(row.source_site, 0) + 1
        return _group(counts)


class FakeRequestRepository:
    def __init__(self, created: list[datetime] | None = None) -> None:
        self.created = list(created or [])

    async def count_created_between(self, session: Any, start, end, source_site=None) -> int:
        return sum(1 for moment in self.created if start <= moment < end)
