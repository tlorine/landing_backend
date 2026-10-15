from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.repositories.site_visits import SiteVisitRepository
from app.services.periods import shift_months

logger = logging.getLogger(__name__)

PURGE_INTERVAL_SECONDS = 6 * 60 * 60


class VisitRetentionWorker:
    """Deletes visits past the retention period and salts older than yesterday."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        repository: SiteVisitRepository,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._settings = settings

    async def run(self) -> None:
        while True:
            try:
                await self.purge_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Visit retention purge failed")
            await asyncio.sleep(PURGE_INTERVAL_SECONDS)

    async def purge_once(self, now: datetime | None = None) -> tuple[int, int]:
        tz = self._settings.stats_zone
        local_now = (now or datetime.now(UTC)).astimezone(tz)
        cutoff_day = shift_months(local_now.date(), -self._settings.visits_retention_months)
        older_than = datetime.combine(cutoff_day, time.min, tzinfo=tz)
        yesterday = local_now.date() - timedelta(days=1)

        async with self._session_factory() as session:
            async with session.begin():
                visits = await self._repository.purge(session, older_than)
                salts = await self._repository.purge_salts(session, yesterday)
        logger.info("Visit retention purge: visits_deleted=%s salts_deleted=%s", visits, salts)
        return visits, salts
