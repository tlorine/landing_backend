import hashlib
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import AnalyticsEvent, AnalyticsSession
from app.schemas.analytics import AnalyticsEventCreate


class EventConflict(Exception):
    pass


class AnalyticsRepository:
    async def insert_event(
        self, session: AsyncSession, event: AnalyticsEventCreate, country: str | None
    ) -> bool:
        payload_hash = hashlib.sha256(event.model_dump_json().encode()).hexdigest()
        values = event.model_dump(exclude={"entry_context"})
        values.update(payload_hash=payload_hash, country=country)
        statement = (
            insert(AnalyticsEvent)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[AnalyticsEvent.source_site, AnalyticsEvent.event_id]
            )
            .returning(AnalyticsEvent.event_id)
        )
        inserted = (await session.execute(statement)).scalar_one_or_none()
        if inserted is None:
            original = (
                await session.execute(
                    select(AnalyticsEvent.payload_hash).where(
                        AnalyticsEvent.source_site == event.source_site,
                        AnalyticsEvent.event_id == event.event_id,
                    )
                )
            ).scalar_one()
            if original != payload_hash:
                raise EventConflict()
            return False
        return True

    async def update_session(
        self, session: AsyncSession, event: AnalyticsEventCreate, country: str | None
    ) -> None:
        # Only confirmed page_view events establish attribution. A delayed earlier view wins
        # atomically, regardless of which transaction arrived first.
        if event.session_id is None or event.event_type != "page_view":
            return
        context = event.entry_context
        source = context.utm_source if context else None
        referrer = context.referrer_host if context else None
        statement = insert(AnalyticsSession).values(
            source_site=event.source_site,
            session_id=event.session_id,
            started_at=event.occurred_at,
            entry_event_id=event.event_id,
            entry_locale=event.locale,
            country=country,
            source_type="utm" if source else "referrer" if referrer else "direct_unknown",
            source_value=source or referrer,
            utm_medium=context.utm_medium if context else None,
            utm_campaign=context.utm_campaign if context else None,
        )
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[AnalyticsSession.source_site, AnalyticsSession.session_id],
            set_={
                key: getattr(excluded, key)
                for key in (
                    "started_at",
                    "entry_event_id",
                    "entry_locale",
                    "country",
                    "source_type",
                    "source_value",
                    "utm_medium",
                    "utm_campaign",
                )
            },
            where=tuple_(excluded.started_at, excluded.entry_event_id)
            < tuple_(AnalyticsSession.started_at, AnalyticsSession.entry_event_id),
        )
        await session.execute(statement)

    async def purge_batch(self, session: AsyncSession, cutoff: datetime, limit: int = 5000) -> int:
        from sqlalchemy import delete

        expired = (
            select(AnalyticsEvent.source_site, AnalyticsEvent.event_id)
            .where(AnalyticsEvent.received_at < cutoff)
            .limit(limit)
        )
        result = await session.execute(
            delete(AnalyticsEvent).where(
                tuple_(AnalyticsEvent.source_site, AnalyticsEvent.event_id).in_(expired)
            )
        )
        return result.rowcount
