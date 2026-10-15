from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.bot.commands import Command, CommandError, parse_command
from app.bot.formatting import (
    STATS_ERROR_TEXT,
    THROTTLED_TEXT,
    format_command_error,
    format_help,
    format_sources_report,
    format_visitors_report,
)
from app.core.config import Settings
from app.services.telegram_bot import TelegramApiError, TelegramBotApi, TelegramConflictError
from app.services.visit_stats import VisitStatsService

logger = logging.getLogger(__name__)

MAX_MESSAGE_AGE_SECONDS = 120
COMMAND_INTERVAL_SECONDS = 3.0
CONFLICT_RETRY_SECONDS = 60.0
MAX_BACKOFF_SECONDS = 60.0


class TelegramCommandWorker:
    """Long-polls the Bot API and answers stats commands in the configured chat only."""

    def __init__(
        self,
        api: TelegramBotApi,
        stats_service: VisitStatsService,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api = api
        self._stats = stats_service
        self._settings = settings
        self._chat_id = str(settings.telegram_chat_id)
        self._clock = clock
        self._bot_username: str | None = None
        self._offset: int | None = None
        self._last_command_at: dict[str, float] = {}

    async def run(self) -> None:
        await self._start()
        backoff = 1.0
        while True:
            try:
                updates = await self._api.get_updates(
                    self._offset, self._settings.telegram_poll_timeout_seconds
                )
            except asyncio.CancelledError:
                raise
            except TelegramConflictError:
                logger.error(
                    "Telegram getUpdates conflict (409): a webhook is set for this bot or another "
                    "process polls it. Remove the webhook or stop the other consumer; retrying in "
                    "%ss",
                    int(CONFLICT_RETRY_SECONDS),
                )
                await asyncio.sleep(CONFLICT_RETRY_SECONDS)
                continue
            except Exception as exc:
                logger.warning("Telegram getUpdates failed (%s); retrying in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            backoff = 1.0
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    self._offset = update_id + 1
                try:
                    await self.handle_update(update)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Unexpected error while handling a Telegram update")

    async def _start(self) -> None:
        if not self._chat_id.lstrip("-").isdigit():
            logger.warning(
                "TELEGRAM_CHAT_ID is not a numeric chat id; bot commands will never match it"
            )
        backoff = 1.0
        while self._bot_username is None:
            try:
                me = await self._api.get_me()
                self._bot_username = str(me.get("username") or "")
            except TelegramApiError as exc:
                logger.warning("Telegram getMe failed (%s); retrying in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
        try:
            await self._api.set_my_commands(self._chat_id)
        except TelegramApiError as exc:
            logger.warning("Telegram setMyCommands failed (%s)", exc)
        logger.info("Telegram command worker started")

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        chat_id = str(chat.get("id")) if isinstance(chat, dict) else None
        if chat_id != self._chat_id:
            logger.debug("Ignoring a Telegram message from another chat")
            return
        text = message.get("text")
        if not isinstance(text, str):
            return
        sent_at = message.get("date")
        if not isinstance(sent_at, int) or time.time() - sent_at > MAX_MESSAGE_AGE_SECONDS:
            logger.info("Ignoring a stale Telegram message")
            return

        parsed = parse_command(text, self._bot_username)
        if parsed is None:
            return
        message_id = message.get("message_id")
        reply_to = message_id if isinstance(message_id, int) else None

        now = self._clock()
        last = self._last_command_at.get(chat_id)
        if last is not None and now - last < COMMAND_INTERVAL_SECONDS:
            await self._reply(chat_id, THROTTLED_TEXT, reply_to)
            return
        self._last_command_at[chat_id] = now

        await self._reply(chat_id, await self._render(parsed), reply_to)

    async def _render(self, parsed: Command | CommandError) -> str:
        if isinstance(parsed, CommandError):
            return format_command_error(parsed.message)
        if parsed.name == "help" or parsed.period is None:
            return format_help()
        try:
            now = datetime.now(UTC)
            if parsed.name == "visits":
                return format_visitors_report(await self._stats.visitors_report(parsed.period, now))
            return format_sources_report(await self._stats.sources_report(parsed.period, now))
        except Exception:
            logger.exception("Failed to build visit statistics for /%s", parsed.name)
            return STATS_ERROR_TEXT

    async def _reply(self, chat_id: str, text: str, reply_to: int | None) -> None:
        try:
            await self._api.send_message(chat_id, text, reply_to_message_id=reply_to)
        except TelegramApiError as exc:
            logger.warning("Telegram sendMessage failed (%s)", exc)
