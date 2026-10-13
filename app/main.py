from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.errors import (
    database_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import SessionFactory, engine
from app.repositories.notification_outbox import NotificationOutboxRepository
from app.services.notification_worker import NotificationWorker
from app.services.telegram import TelegramNotifier

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    worker_task: asyncio.Task[None] | None = None
    notifier: TelegramNotifier | None = None

    if settings.telegram_enabled:
        bot_token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if bot_token is None or chat_id is None:
            raise RuntimeError("Telegram credentials are incomplete.")
        notifier = TelegramNotifier(bot_token, chat_id)
        worker = NotificationWorker(
            outbox_repository=NotificationOutboxRepository(SessionFactory),
            notifier=notifier,
            settings=settings,
        )
        worker_task = asyncio.create_task(worker.run(), name="telegram-notification-worker")
        logger.info("Telegram notification worker started")
    else:
        logger.warning(
            "Telegram notifications are disabled; configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )

    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task
        if notifier is not None:
            await notifier.aclose()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="API для приёма заявок с лендингов и уведомления команды в Telegram.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(SQLAlchemyError, database_error_handler)
app.add_exception_handler(Exception, unexpected_error_handler)
app.include_router(api_router, prefix="/api/v1")
