from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.notification_outbox import NotificationOutbox
from app.models.service_request import ServiceRequest


@dataclass(frozen=True, slots=True)
class ClaimedNotification:
    outbox_id: uuid.UUID
    attempts: int
    request_data: dict[str, str | None]


class NotificationOutboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue(self, session: AsyncSession, request_id: uuid.UUID) -> None:
        session.add(NotificationOutbox(request_id=request_id))
        await session.flush()

    async def claim_next(self) -> ClaimedNotification | None:
        now = datetime.now(UTC)
        stale_lock_before = now - timedelta(minutes=5)
        eligible = or_(
            and_(
                NotificationOutbox.status == "pending",
                NotificationOutbox.next_attempt_at <= now,
            ),
            and_(
                NotificationOutbox.status == "processing",
                NotificationOutbox.locked_at <= stale_lock_before,
            ),
        )
        statement = (
            select(NotificationOutbox, ServiceRequest)
            .join(ServiceRequest, NotificationOutbox.request_id == ServiceRequest.id)
            .where(eligible)
            .order_by(NotificationOutbox.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True, of=NotificationOutbox)
        )

        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(statement)
                row = result.first()
                if row is None:
                    return None

                outbox, request = row
                outbox.status = "processing"
                outbox.locked_at = now
                outbox.attempts += 1
                await session.flush()

                request_data = {
                    "id": str(request.id),
                    "name": request.name,
                    "budget": request.budget,
                    "contact": request.contact,
                    "description": request.description,
                    "source_site": request.source_site,
                    "created_at": request.created_at.isoformat(),
                }
                return ClaimedNotification(
                    outbox_id=outbox.id,
                    attempts=outbox.attempts,
                    request_data=request_data,
                )

    async def mark_sent(self, outbox_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(NotificationOutbox)
                    .where(NotificationOutbox.id == outbox_id)
                    .values(
                        status="sent",
                        sent_at=datetime.now(UTC),
                        locked_at=None,
                        last_error=None,
                    )
                )

    async def mark_failed(
        self,
        outbox_id: uuid.UUID,
        error_message: str,
        retry_delay_seconds: int,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(NotificationOutbox)
                    .where(NotificationOutbox.id == outbox_id)
                    .values(
                        status="pending",
                        next_attempt_at=now + timedelta(seconds=retry_delay_seconds),
                        locked_at=None,
                        last_error=error_message[:1000],
                    )
                )
