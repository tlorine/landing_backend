import hashlib
import json
import logging
from time import monotonic

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.repositories.analytics import EventConflict
from app.schemas.analytics import AnalyticsBatch
from app.schemas.analytics_reports import ErrorResponse, IngestionResponse
from app.services.analytics_ingestion import AnalyticsIngestionService
from app.services.client_context import client_context
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.user_agent import is_bot

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    responses={code: {"model": ErrorResponse} for code in (400, 403, 409, 413, 415, 422, 429, 503)},
)
logger = logging.getLogger(__name__)
service = AnalyticsIngestionService()
limiter = SlidingWindowRateLimiter(settings.analytics_rate_limit_per_minute)


def error(status, code, message, headers=None):
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}, headers=headers
    )


@router.post(
    "/events",
    response_model=IngestionResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                media: {"schema": {"$ref": "#/components/schemas/AnalyticsBatch"}}
                for media in ("application/json", "text/plain")
            },
        }
    },
)
async def events(request: Request, session: AsyncSession = Depends(get_session)):
    if not settings.analytics_enabled:
        return error(503, "analytics_disabled", "Сбор аналитики отключён.")
    if request.headers.get("origin") and request.headers["origin"] not in settings.cors_origins:
        return error(403, "origin_not_allowed", "Источник не разрешён.")
    if request.headers.get("content-type", "").split(";")[0].lower() not in (
        "text/plain",
        "application/json",
    ):
        return error(415, "unsupported_media_type", "Ожидается JSON.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            return error(413, "payload_too_large", "Слишком большой запрос.")
    client = client_context(request)
    ua = request.headers.get("user-agent", "")
    key = hashlib.sha256(f"{client.ip}\n{ua}".encode()).hexdigest()
    if not limiter.allow(key):
        return error(429, "rate_limited", "Слишком много запросов.", {"Retry-After": "60"})
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return error(400, "invalid_json", "Тело запроса должно быть JSON.")
    try:
        batch = AnalyticsBatch.model_validate(payload)
        service.validate(batch)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None
    except ValueError as exc:
        return error(422, "validation_error", str(exc))
    if not ua or is_bot(ua):
        return {"accepted": 0, "duplicates": 0, "ignored": len(batch.events)}
    try:
        started = monotonic()
        result = await service.record(session, batch, client, ua)
        logger.info(
            "Analytics ingestion: accepted=%s duplicates=%s latency_ms=%.1f",
            result["accepted"],
            result["duplicates"],
            (monotonic() - started) * 1000,
        )
        return result
    except EventConflict:
        return error(409, "event_conflict", "event_id уже используется другим событием.")
