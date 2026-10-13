from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.repositories.notification_outbox import NotificationOutboxRepository
from app.services.telegram import TelegramDeliveryError, TelegramNotifier

logger = logging.getLogger(__name__)


class NotificationWorker:
    """Background outbox consumer with exponential retry and stale-lock recovery."""

    def __init__(
        self,
        outbox_repository: NotificationOutboxRepository,
        notifier: TelegramNotifier,
        settings: Settings,
    ) -> None:
        self._outbox_repository = outbox_repository
        self._notifier = notifier
        self._settings = settings

    async def run(self) -> None:
        while True:
            try:
                processed = await self.process_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in Telegram notification worker")
                processed = False

            if not processed:
                await asyncio.sleep(self._settings.notification_poll_interval_seconds)

    async def process_one(self) -> bool:
        job = await self._outbox_repository.claim_next()
        if job is None:
            return False

        try:
            await self._notifier.send_request(job.request_data)
        except TelegramDeliveryError as exc:
            retry_delay = min(
                5 * (2 ** min(job.attempts - 1, 10)),
                self._settings.notification_retry_max_seconds,
            )
            await self._outbox_repository.mark_failed(
                job.outbox_id,
                error_message=str(exc),
                retry_delay_seconds=retry_delay,
            )
            logger.warning(
                "Telegram notification delivery failed: outbox_id=%s attempt=%s "
                "retry_in=%ss reason=%s",
                job.outbox_id,
                job.attempts,
                retry_delay,
                exc,
            )
        except Exception as exc:
            # Unexpected errors are retried too, but only the exception type is persisted/logged.
            retry_delay = min(
                5 * (2 ** min(job.attempts - 1, 10)),
                self._settings.notification_retry_max_seconds,
            )
            await self._outbox_repository.mark_failed(
                job.outbox_id,
                error_message=f"Unexpected error ({type(exc).__name__})",
                retry_delay_seconds=retry_delay,
            )
            logger.exception(
                "Unexpected notification error: outbox_id=%s attempt=%s",
                job.outbox_id,
                job.attempts,
            )
        else:
            await self._outbox_repository.mark_sent(job.outbox_id)
            logger.info("Telegram notification sent: outbox_id=%s", job.outbox_id)

        return True
