"""Bounded cleanup; no unbounded long write transaction or per-process counters."""

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import and_, delete, exists, select

from app.core.config import Settings
from app.models.analytics import AdminLoginAttempt, AdminSession, AnalyticsEvent, AnalyticsSession
from app.repositories.analytics import AnalyticsRepository
from app.services.periods import shift_months

logger = logging.getLogger(__name__)


class AnalyticsRetentionWorker:
    def __init__(self, factory, config: Settings):
        self.factory = factory
        self.config = config
        self.repository = AnalyticsRepository()

    async def purge_once(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        cutoff = datetime.combine(
            shift_months(now.date(), -self.config.analytics_retention_months), time.min, UTC
        )
        removed = 0
        # At most 100k events per cycle. Each batch commits separately.
        for _ in range(20):
            async with self.factory() as session, session.begin():
                count = await self.repository.purge_batch(session, cutoff)
            removed += count
            if count < 5000:
                break
        async with self.factory() as session, session.begin():
            stale_sessions = (
                select(AnalyticsSession.source_site, AnalyticsSession.session_id)
                .where(
                    AnalyticsSession.started_at < cutoff,
                    ~exists(
                        select(AnalyticsEvent.event_id).where(
                            and_(
                                AnalyticsEvent.source_site == AnalyticsSession.source_site,
                                AnalyticsEvent.session_id == AnalyticsSession.session_id,
                            )
                        )
                    ),
                )
                .limit(5000)
            )
            from sqlalchemy import tuple_

            await session.execute(
                delete(AnalyticsSession).where(
                    tuple_(AnalyticsSession.source_site, AnalyticsSession.session_id).in_(
                        stale_sessions
                    )
                )
            )
            await session.execute(delete(AdminSession).where(AdminSession.expires_at < now))
            await session.execute(
                delete(AdminLoginAttempt).where(
                    AdminLoginAttempt.window_started_at < now - timedelta(hours=1)
                )
            )
        return removed

    async def run(self) -> None:
        while True:
            try:
                count = await self.purge_once()
                logger.info("Analytics retention: events_deleted=%s", count)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Analytics retention failed")
            await asyncio.sleep(6 * 60 * 60)
