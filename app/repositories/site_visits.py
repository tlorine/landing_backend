from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_visit import SiteVisit, VisitSalt

BREAKDOWN_COLUMNS = {
    "country": SiteVisit.country,
    "device_type": SiteVisit.device_type,
    "os": SiteVisit.os,
    "browser": SiteVisit.browser,
    "locale": SiteVisit.locale,
    "referrer_host": SiteVisit.referrer_host,
}


@dataclass(frozen=True, slots=True)
class VisitTotals:
    visits: int
    visitors: int


@dataclass(frozen=True, slots=True)
class UtmCampaignRow:
    utm_source: str | None
    utm_medium: str | None
    utm_campaign: str | None
    visits: int


class SiteVisitRepository:
    async def add(self, session: AsyncSession, visit: SiteVisit) -> None:
        session.add(visit)
        await session.flush()

    async def get_or_create_salt(self, session: AsyncSession, day: date) -> bytes:
        # Concurrent first visits of a day race safely: only one salt is ever stored.
        await session.execute(
            insert(VisitSalt)
            .values(day=day, salt=secrets.token_bytes(32))
            .on_conflict_do_nothing(index_elements=[VisitSalt.day])
        )
        result = await session.execute(select(VisitSalt.salt).where(VisitSalt.day == day))
        return bytes(result.scalar_one())

    async def purge(self, session: AsyncSession, older_than: datetime) -> int:
        result = await session.execute(delete(SiteVisit).where(SiteVisit.occurred_at < older_than))
        return result.rowcount or 0

    async def purge_salts(self, session: AsyncSession, before_day: date) -> int:
        result = await session.execute(delete(VisitSalt).where(VisitSalt.day < before_day))
        return result.rowcount or 0

    @staticmethod
    def _window(
        start: datetime, end: datetime, source_site: str | None
    ) -> list[ColumnElement[bool]]:
        conditions = [SiteVisit.occurred_at >= start, SiteVisit.occurred_at < end]
        if source_site is not None:
            conditions.append(SiteVisit.source_site == source_site)
        return conditions

    async def totals(
        self,
        session: AsyncSession,
        start: datetime,
        end: datetime,
        source_site: str | None = None,
    ) -> VisitTotals:
        result = await session.execute(
            select(func.count(), func.count(SiteVisit.visitor_hash.distinct())).where(
                *self._window(start, end, source_site)
            )
        )
        visits, visitors = result.one()
        return VisitTotals(visits=visits, visitors=visitors)

    async def breakdown(
        self,
        session: AsyncSession,
        column: str,
        start: datetime,
        end: datetime,
        limit: int | None = None,
        source_site: str | None = None,
    ) -> list[tuple[str | None, int]]:
        target = BREAKDOWN_COLUMNS[column]
        visits = func.count().label("visits")
        statement = (
            select(target, visits)
            .where(*self._window(start, end, source_site))
            .group_by(target)
            .order_by(visits.desc(), target.asc().nulls_last())
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await session.execute(statement)
        return [(value, count) for value, count in result.all()]

    async def utm_campaigns(
        self,
        session: AsyncSession,
        start: datetime,
        end: datetime,
        limit: int,
        source_site: str | None = None,
    ) -> list[UtmCampaignRow]:
        columns = (SiteVisit.utm_source, SiteVisit.utm_medium, SiteVisit.utm_campaign)
        visits = func.count().label("visits")
        result = await session.execute(
            select(*columns, visits)
            .where(
                *self._window(start, end, source_site),
                or_(*(column.is_not(None) for column in columns)),
            )
            .group_by(*columns)
            .order_by(visits.desc(), *(column.asc().nulls_last() for column in columns))
            .limit(limit)
        )
        return [UtmCampaignRow(*row) for row in result.all()]

    async def sites(
        self, session: AsyncSession, start: datetime, end: datetime
    ) -> list[tuple[str, int]]:
        visits = func.count().label("visits")
        result = await session.execute(
            select(SiteVisit.source_site, visits)
            .where(*self._window(start, end, None))
            .group_by(SiteVisit.source_site)
            .order_by(visits.desc(), SiteVisit.source_site.asc())
        )
        return [(site, count) for site, count in result.all()]
