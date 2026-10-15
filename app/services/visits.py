from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.site_visit import SiteVisit
from app.repositories.site_visits import SiteVisitRepository
from app.schemas.site_visit import VisitCreate
from app.services.user_agent import parse_user_agent


def visitor_hash(salt: bytes, ip: str, user_agent: str, source_site: str) -> str:
    material = salt + f"{ip}\n{user_agent}\n{source_site}".encode()
    return hashlib.sha256(material).hexdigest()


class VisitService:
    """Stores anonymous visits; the IP address only feeds the salted daily hash."""

    def __init__(self, repository: SiteVisitRepository, tz: ZoneInfo) -> None:
        self._repository = repository
        self._tz = tz
        # Today's salt never changes once stored, so one cached day saves a query per visit.
        self._cached_salt: tuple[date, bytes] | None = None

    async def record(
        self,
        session: AsyncSession,
        payload: VisitCreate,
        ip: str,
        user_agent: str,
        country: str | None,
        now: datetime | None = None,
    ) -> None:
        today = (now or datetime.now(UTC)).astimezone(self._tz).date()
        ua_info = parse_user_agent(user_agent)
        async with session.begin():
            salt = await self._salt_for(session, today)
            visit = SiteVisit(
                source_site=payload.source_site,
                path=payload.path,
                locale=payload.locale,
                country=country,
                device_type=payload.device_type or ua_info.device_type,
                os=ua_info.os,
                browser=ua_info.browser,
                referrer_host=payload.referrer_host,
                utm_source=payload.utm_source,
                utm_medium=payload.utm_medium,
                utm_campaign=payload.utm_campaign,
                visitor_hash=visitor_hash(salt, ip, user_agent, payload.source_site),
            )
            await self._repository.add(session, visit)
        # Cache only after commit, so a rolled-back salt is never reused.
        self._cached_salt = (today, salt)

    async def _salt_for(self, session: AsyncSession, day: date) -> bytes:
        if self._cached_salt is not None and self._cached_salt[0] == day:
            return self._cached_salt[1]
        return await self._repository.get_or_create_salt(session, day)
