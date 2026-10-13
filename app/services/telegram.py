from __future__ import annotations

from collections.abc import Mapping

import httpx
from pydantic import SecretStr


class TelegramDeliveryError(RuntimeError):
    """A safe-to-log Telegram delivery error that never includes the bot token or URL."""


class TelegramNotifier:
    def __init__(self, bot_token: SecretStr, chat_id: str) -> None:
        self._bot_token = bot_token.get_secret_value()
        self._chat_id = chat_id
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

    async def send_request(self, request_data: Mapping[str, str | None]) -> None:
        message = self._format_message(request_data)
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        try:
            response = await self._client.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Do not stringify httpx exceptions: their request URL may contain the bot token.
            raise TelegramDeliveryError(
                f"Telegram transport/response error ({type(exc).__name__})."
            ) from None

        if not isinstance(result, dict) or result.get("ok") is not True:
            raise TelegramDeliveryError("Telegram API rejected the notification.")

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _format_message(request_data: Mapping[str, str | None]) -> str:
        description = request_data.get("description") or "—"
        truncation_note = (
            "\n… (описание обрезано только в уведомлении)" if len(description) > 2800 else ""
        )
        description = description[:2800] + truncation_note

        return "\n".join(
            [
                "🆕 Новая заявка",
                f"ID: {request_data.get('id') or '—'}",
                f"Сайт: {request_data.get('source_site') or '—'}",
                f"Имя: {request_data.get('name') or 'не указано'}",
                f"Бюджет: {request_data.get('budget') or 'не указан'}",
                f"Контакт: {request_data.get('contact') or '—'}",
                f"Создана: {request_data.get('created_at') or '—'}",
                "",
                "Описание:",
                description,
            ]
        )
