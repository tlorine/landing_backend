from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.analytics import AnalyticsRepository
from app.repositories.site_visits import SiteVisitRepository
from app.schemas.analytics import AnalyticsBatch
from app.schemas.site_visit import VisitCreate
from app.services.analytics_manifest import validate_event
from app.services.client_context import ClientContext
from app.services.visits import VisitService


class AnalyticsIngestionService:
    def __init__(self) -> None:
        self.repository = AnalyticsRepository()
        self.visits = VisitService(SiteVisitRepository(), settings.stats_zone)

    def validate(self, batch: AnalyticsBatch, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        for event in batch.events:
            if event.source_site not in settings.analytics_sites:
                raise ValueError("source_site is not enabled")
            if not now - timedelta(hours=24) <= event.occurred_at <= now + timedelta(minutes=5):
                raise ValueError("occurred_at is outside ingestion window")
            if not settings.analytics_sessions_enabled and event.session_id is not None:
                raise ValueError("session tracking is disabled")
            if event.entry_context and event.entry_context.started_at > event.occurred_at:
                raise ValueError("entry started_at must not follow event time")
            validate_event(event)

    async def record(
        self, session: AsyncSession, batch: AnalyticsBatch, client: ClientContext, user_agent: str
    ) -> dict[str, int]:
        accepted = duplicates = 0
        async with session.begin():
            lock_keys = sorted(
                {
                    f"analytics-session:{e.source_site}:{e.session_id}"
                    for e in batch.events
                    if e.session_id
                }
            )
            for key in lock_keys:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
                )
            # Stable lock order prevents deadlocks between overlapping retry batches.
            for event in sorted(batch.events, key=lambda e: (e.source_site, str(e.event_id))):
                inserted = await self.repository.insert_event(session, event, client.country)
                if not inserted:
                    duplicates += 1
                    continue
                accepted += 1
                await self.repository.update_session(session, event, client.country)
                if event.event_type == "page_view":
                    context = event.entry_context
                    visit = VisitCreate(
                        source_site=event.source_site,
                        path=event.path,
                        locale=event.locale,
                        device_type=event.device_type,
                        referrer_host=context.referrer_host if context else None,
                        utm_source=context.utm_source if context else None,
                        utm_medium=context.utm_medium if context else None,
                        utm_campaign=context.utm_campaign if context else None,
                    )
                    await self.visits.record_in_transaction(
                        session, visit, client.ip, user_agent, client.country
                    )
        return {"accepted": accepted, "duplicates": duplicates}
