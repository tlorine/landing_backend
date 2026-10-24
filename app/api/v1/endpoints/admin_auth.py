import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.analytics import error
from app.core.config import settings
from app.db.session import get_session
from app.schemas.analytics import LoginInput
from app.schemas.analytics_reports import AuthResponse, CsrfResponse, ErrorResponse
from app.services.admin_auth import (
    BOOTSTRAP_COOKIE,
    COOKIE,
    COOKIE_PATH,
    AdminAuthService,
)
from app.services.client_context import client_context

router = APIRouter(
    prefix="/admin/auth",
    tags=["admin-auth"],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 422, 429, 503)},
)
service = AdminAuthService()


@dataclass(frozen=True)
class AdminPrincipal:
    username: str
    csrf_token: str
    token_hash: str


def enabled() -> None:
    if not settings.admin_enabled:
        raise HTTPException(status_code=404, detail="Admin is disabled")


def check_origin(request: Request) -> bool:
    return request.headers.get("origin") in settings.admin_origins


async def require_admin(
    request: Request, session: AsyncSession = Depends(get_session)
) -> AdminPrincipal:
    enabled()
    user = await service.authenticate(session, request.cookies.get(COOKIE))
    principal = AdminPrincipal(user.username, user.csrf_token, user.token_hash) if user else None
    # Release the read transaction; reports start their own REPEATABLE READ snapshot.
    await session.rollback()
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


Admin = Annotated[AdminPrincipal, Depends(require_admin)]


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path=COOKIE_PATH,
    )


@router.get("/csrf", response_model=CsrfResponse)
async def csrf(response: Response):
    enabled()
    token = secrets.token_urlsafe(32)
    set_cookie(response, BOOTSTRAP_COOKIE, token, 600)
    return {"csrf_token": token}


@router.post("/login", response_model=AuthResponse)
async def login(
    request: Request,
    payload: LoginInput,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    enabled()
    cookie = request.cookies.get(BOOTSTRAP_COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    if not check_origin(request) or not cookie or not secrets.compare_digest(cookie, header):
        return error(403, "csrf_failed", "Обновите страницу входа и повторите попытку.")
    result, code = await service.login(
        session, payload.username, payload.password, client_context(request).ip
    )
    if result is None:
        status = 429 if code == "rate_limited" else 401
        return error(
            status,
            code,
            "Вход временно ограничен." if status == 429 else "Неверные данные входа.",
            {"Retry-After": "900"} if status == 429 else None,
        )
    token, record = result
    # Revoke an existing browser session on successful re-login (rotation).
    from sqlalchemy import delete

    from app.models.analytics import AdminSession
    from app.services.admin_auth import digest

    old = request.cookies.get(COOKIE)
    if old:
        async with session.begin():
            await session.execute(
                delete(AdminSession).where(AdminSession.token_hash == digest(old))
            )
    set_cookie(response, COOKIE, token, settings.admin_session_hours * 3600)
    response.delete_cookie(BOOTSTRAP_COOKIE, path=COOKIE_PATH)
    return {"username": record.username, "csrf_token": record.csrf_token}


@router.get("/me", response_model=AuthResponse)
async def me(admin: Admin):
    return {"username": admin.username, "csrf_token": admin.csrf_token}


@router.post("/logout", status_code=204)
async def logout(
    request: Request, admin: Admin, response: Response, session: AsyncSession = Depends(get_session)
):
    if not check_origin(request) or not secrets.compare_digest(
        admin.csrf_token, request.headers.get("x-csrf-token", "")
    ):
        return error(403, "csrf_failed", "Проверка запроса не пройдена.")
    from sqlalchemy import delete

    from app.models.analytics import AdminSession

    async with session.begin():
        await session.execute(
            delete(AdminSession).where(AdminSession.token_hash == admin.token_hash)
        )
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.status_code = 204
    return response
