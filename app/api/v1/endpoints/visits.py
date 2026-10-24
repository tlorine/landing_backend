import hashlib
import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.repositories.site_visits import SiteVisitRepository
from app.schemas.site_visit import VisitCreate
from app.services.client_context import client_context
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.user_agent import is_bot
from app.services.visits import VisitService

router = APIRouter(prefix="/visits", tags=["visits"])

MAX_BODY_BYTES = 2048
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
# Cloudflare uses XX for unknown and T1 for Tor; neither is a country.
_UNKNOWN_COUNTRIES = {"XX", "T1"}

_visit_service = VisitService(repository=SiteVisitRepository(), tz=settings.stats_zone)
_rate_limiter = SlidingWindowRateLimiter(limit=settings.visits_rate_limit_per_minute)


def get_visit_service() -> VisitService:
    return _visit_service


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _rate_limiter


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def _country(request: Request) -> str | None:
    return client_context(request).country


def _client_ip(request: Request) -> str:
    return client_context(request).ip


async def _read_limited_body(request: Request) -> bytes | None:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return None
    return bytes(body)


@router.post("", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def create_visit(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[VisitService, Depends(get_visit_service)],
    limiter: Annotated[SlidingWindowRateLimiter, Depends(get_rate_limiter)],
) -> Response:
    # Accepts both text/plain (navigator.sendBeacon, no CORS preflight) and application/json.
    body = await _read_limited_body(request)
    if body is None:
        return _error(413, "payload_too_large", "Слишком большой запрос.")

    user_agent = request.headers.get("user-agent", "").strip()
    if not user_agent or is_bot(user_agent):
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    ip = _client_ip(request)
    limit_key = hashlib.sha256(f"{ip}{user_agent}".encode()).hexdigest()
    if not limiter.allow(limit_key):
        return _error(429, "rate_limited", "Слишком много запросов.")

    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return _error(400, "invalid_json", "Тело запроса должно быть JSON.")

    try:
        payload = VisitCreate.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None

    await service.record(session, payload, ip=ip, user_agent=user_agent, country=_country(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
