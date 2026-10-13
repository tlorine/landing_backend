from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def _validation_message(error: dict[str, Any]) -> str:
    error_type = error.get("type")
    if error_type == "missing":
        return "Обязательное поле."
    if error_type == "string_too_short":
        return "Слишком короткое значение."
    if error_type == "string_too_long":
        return "Слишком длинное значение."

    message = str(error.get("msg", "Некорректное значение."))
    prefix = "Value error, "
    return message.removeprefix(prefix)


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details: list[dict[str, str]] = []
    for error in exc.errors():
        location = [
            str(part) for part in error.get("loc", ()) if part not in {"body", "query", "path"}
        ]
        details.append(
            {
                "field": ".".join(location) or "body",
                "message": _validation_message(error),
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Проверьте введённые данные.",
                "details": details,
            }
        },
    )


async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.error(
        "Database error while handling %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "Сервис временно недоступен. Попробуйте ещё раз позже.",
            }
        },
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled error while handling %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Внутренняя ошибка сервера.",
            }
        },
    )
