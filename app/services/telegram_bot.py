from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

BOT_COMMANDS = [
    {"command": "visits", "description": "Посещения: люди, страны, устройства"},
    {"command": "sources", "description": "Откуда пришли посетители"},
    {"command": "help", "description": "Справка"},
]


class TelegramApiError(RuntimeError):
    """A safe-to-log Bot API error that never includes the bot token or URL."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelegramConflictError(TelegramApiError):
    """getUpdates returned 409: a webhook is set or another consumer is polling."""


class TelegramBotApi:
    def __init__(self, bot_token: SecretStr, poll_timeout_seconds: int = 25) -> None:
        self._bot_token = bot_token.get_secret_value()
        # The read timeout must outlast the long-polling timeout.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(poll_timeout_seconds + 10.0, connect=5.0)
        )

    async def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"https://api.telegram.org/bot{self._bot_token}/{method}"
        try:
            response = await self._client.post(url, json=payload or {})
        except httpx.HTTPError as exc:
            # Do not stringify httpx exceptions: their request URL contains the bot token.
            raise TelegramApiError(f"{method}: transport error ({type(exc).__name__}).") from None

        if response.status_code == 409:
            raise TelegramConflictError(f"{method}: conflict (409).", status_code=409)
        try:
            result = response.json()
        except ValueError:
            result = None
        if response.is_error or not isinstance(result, dict) or result.get("ok") is not True:
            raise TelegramApiError(
                f"{method}: rejected with HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        return result.get("result")

    async def get_me(self) -> dict[str, Any]:
        result = await self._call("getMe")
        return result if isinstance(result, dict) else {}

    async def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result = await self._call("getUpdates", payload)
        return (
            [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []
        )

    async def send_message(
        self, chat_id: str | int, text: str, reply_to_message_id: int | None = None
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to_message_id is not None:
            payload["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        await self._call("sendMessage", payload)

    async def set_my_commands(self, chat_id: str | int) -> None:
        await self._call(
            "setMyCommands",
            {"commands": BOT_COMMANDS, "scope": {"type": "chat", "chat_id": chat_id}},
        )

    async def aclose(self) -> None:
        await self._client.aclose()
