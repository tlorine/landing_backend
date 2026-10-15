from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.services.periods import PERIOD_LIMITS, Period, PeriodError, PeriodUnit

CommandName = Literal["visits", "sources", "help"]

DEFAULT_PERIOD = Period("day", 7)

_UNIT_ALIASES: dict[str, PeriodUnit] = {
    **dict.fromkeys(("d", "д", "день", "дня", "дней", "day", "days"), "day"),
    **dict.fromkeys(("w", "н", "нед", "неделя", "недели", "недель", "week", "weeks"), "week"),
    **dict.fromkeys(("m", "м", "мес", "месяц", "месяца", "месяцев", "month", "months"), "month"),
}
_COMMANDS: dict[str, CommandName] = {
    "visits": "visits",
    "sources": "sources",
    "help": "help",
    "start": "help",
}
_PERIOD_RE = re.compile(r"^(\d{1,4})\s*(\S+)$")

PERIOD_HINT = (
    "Формат периода: число и единица — дни (7d, 7 дней), недели (2w, 2 недели) "
    f"или месяцы (3m, 3 месяца). Лимиты: до {PERIOD_LIMITS['day']} дней, "
    f"{PERIOD_LIMITS['week']} недель, {PERIOD_LIMITS['month']} месяцев."
)


@dataclass(frozen=True, slots=True)
class Command:
    name: CommandName
    period: Period | None = None


@dataclass(frozen=True, slots=True)
class CommandError:
    message: str


def parse_period(argument: str) -> Period | CommandError:
    match = _PERIOD_RE.fullmatch(argument.strip().lower())
    unit = _UNIT_ALIASES.get(match.group(2)) if match else None
    if match is None or unit is None:
        return CommandError(f"Не понял период «{argument.strip()}». {PERIOD_HINT}")
    try:
        return Period(unit, int(match.group(1)))
    except PeriodError:
        return CommandError(f"Период вне допустимого диапазона. {PERIOD_HINT}")


def parse_command(text: str, bot_username: str | None) -> Command | CommandError | None:
    """Parse a chat message; None means the message is not a command for this bot."""
    head, *rest = text.strip().split(maxsplit=1) or [""]
    argument = rest[0] if rest else ""
    if not head.startswith("/"):
        return None
    name, _, mention = head[1:].partition("@")
    if mention and (bot_username is None or mention.lower() != bot_username.lower()):
        return None
    command = _COMMANDS.get(name.lower())
    if command is None:
        return None
    if command == "help":
        return Command("help")

    if not argument:
        return Command(command, DEFAULT_PERIOD)
    period = parse_period(argument)
    if isinstance(period, CommandError):
        return period
    return Command(command, period)
