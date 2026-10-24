"""Keep analytics coverage aligned with the active ingestion configuration."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.models.analytics import AnalyticsCoverage

logger = logging.getLogger(__name__)


class AnalyticsCoverageService:
    def __init__(self, factory, config):
        self.factory = factory
        self.config = config

    async def reconcile(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        for source_site in sorted(set(self.config.analytics_sites)):
            async with self.factory() as session, session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"analytics-coverage:{source_site}"},
                )
                active = list(
                    (
                        await session.scalars(
                            select(AnalyticsCoverage)
                            .where(
                                AnalyticsCoverage.source_site == source_site,
                                AnalyticsCoverage.ended_at.is_(None),
                            )
                            .order_by(AnalyticsCoverage.started_at)
                            .with_for_update()
                        )
                    ).all()
                )
                mode_matches = (
                    len(active) == 1
                    and active[0].sessions_enabled == self.config.analytics_sessions_enabled
                )
                if self.config.analytics_enabled and mode_matches:
                    continue
                if not self.config.analytics_enabled and not active:
                    continue

                for interval in active:
                    interval.ended_at = now
                if self.config.analytics_enabled:
                    session.add(
                        AnalyticsCoverage(
                            source_site=source_site,
                            started_at=now,
                            sessions_enabled=self.config.analytics_sessions_enabled,
                        )
                    )
                logger.info(
                    "Analytics coverage synchronized: site=%s enabled=%s sessions=%s",
                    source_site,
                    self.config.analytics_enabled,
                    self.config.analytics_sessions_enabled,
                )
