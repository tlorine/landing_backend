from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from app.repositories.service_requests import ServiceRequestRepository
from app.repositories.site_visits import SiteVisitRepository
from app.services.analytics_retention import AnalyticsRetentionWorker
from app.services.bot_worker import TelegramCommandWorker
from app.services.notification_worker import NotificationWorker
from app.services.telegram import TelegramNotifier
from app.services.telegram_bot import TelegramBotApi
from app.services.visit_retention import VisitRetentionWorker
from app.services.visit_stats import VisitStatsService

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    worker_task: asyncio.Task[None] | None = None
    notifier: TelegramNotifier | None = None
    command_task: asyncio.Task[None] | None = None
    bot_api: TelegramBotApi | None = None

    # Retention runs regardless of Telegram: old visits and salts must be deleted anyway.
    retention = VisitRetentionWorker(SessionFactory, SiteVisitRepository(), settings)
    retention_task = asyncio.create_task(retention.run(), name="visit-retention-worker")

    analytics_retention = AnalyticsRetentionWorker(SessionFactory, settings)
    analytics_retention_task = asyncio.create_task(
        analytics_retention.run(), name="analytics-retention-worker"
    )

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

        if settings.telegram_commands_enabled:
            bot_api = TelegramBotApi(bot_token, settings.telegram_poll_timeout_seconds)
            stats_service = VisitStatsService(
                session_factory=SessionFactory,
                visit_repository=SiteVisitRepository(),
                request_repository=ServiceRequestRepository(),
                tz=settings.stats_zone,
            )
            command_worker = TelegramCommandWorker(bot_api, stats_service, settings)
            command_task = asyncio.create_task(command_worker.run(), name="telegram-command-worker")
    else:
        logger.warning(
            "Telegram notifications are disabled; configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
        )

    try:
        yield
    finally:
        for task in (worker_task, command_task, retention_task, analytics_retention_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        if notifier is not None:
            await notifier.aclose()
        if bot_api is not None:
            await bot_api.aclose()
        await engine.dispose()


# Interactive docs and the OpenAPI schema are not exposed in production.
_docs_enabled = settings.app_env != "production"

app = FastAPI(
    title=settings.app_name,
    description="API для приёма заявок с лендингов и уведомления команды в Telegram.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
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


@app.middleware("http")
async def private_admin_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/admin"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Vary"] = "Cookie, Origin"
    return response


@app.exception_handler(HTTPException)
async def http_error_handler(request, exc):
    codes = {
        401: "authentication_required",
        403: "forbidden",
        404: "not_found",
        422: "validation_error",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {"code": codes.get(exc.status_code, "http_error"), "message": str(exc.detail)}
        },
        headers=exc.headers,
    )


# Ingestion accepts text/plain beacons through bounded streaming parsing. Register
# its Pydantic model explicitly so offline OpenAPI is equally precise as JSON APIs.
_default_openapi = app.openapi


def analytics_openapi():
    from app.schemas.analytics import AnalyticsBatch

    schema = _default_openapi()
    batch = AnalyticsBatch.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions = batch.pop("$defs", {})
    schema.setdefault("components", {}).setdefault("schemas", {}).update(definitions)
    schema["components"]["schemas"]["AnalyticsBatch"] = batch
    return schema


app.openapi = analytics_openapi
