from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from html import escape

from app.services.periods import PERIOD_LIMITS, Period, ResolvedPeriod
from app.services.visit_stats import ShareRow, SourcesReport, VisitorsReport

MAX_MESSAGE_LENGTH = 4096
_MAX_VALUE_LENGTH = 64

EMPTY_PERIOD_TEXT = "За этот период визитов нет."
STATS_ERROR_TEXT = "Не удалось получить статистику, попробуйте позже."
THROTTLED_TEXT = "Подождите пару секунд."

COUNTRY_NAMES = {
    "RU": "Россия",
    "AM": "Армения",
    "GE": "Грузия",
    "KZ": "Казахстан",
    "BY": "Беларусь",
    "UA": "Украина",
    "UZ": "Узбекистан",
    "KG": "Киргизия",
    "AZ": "Азербайджан",
    "TR": "Турция",
    "AE": "ОАЭ",
    "IL": "Израиль",
    "DE": "Германия",
    "NL": "Нидерланды",
    "GB": "Великобритания",
    "FR": "Франция",
    "PL": "Польша",
    "US": "США",
    "CY": "Кипр",
    "RS": "Сербия",
    "ES": "Испания",
    "IT": "Италия",
    "FI": "Финляндия",
    "LV": "Латвия",
    "LT": "Литва",
    "EE": "Эстония",
    "TH": "Таиланд",
    "ID": "Индонезия",
    "CN": "Китай",
}
_DEVICE_NAMES = {"mobile": "телефон", "desktop": "компьютер", "tablet": "планшет"}
_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_UNIT_FORMS = {
    "day": ("день", "дня", "дней"),
    "week": ("неделя", "недели", "недель"),
    "month": ("месяц", "месяца", "месяцев"),
}


def plural(count: int, forms: tuple[str, str, str]) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return forms[0]
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return forms[1]
    return forms[2]


def period_label(period: Period) -> str:
    return f"{period.count} {plural(period.count, _UNIT_FORMS[period.unit])}"


def _day(moment: datetime, with_month: bool = True, with_year: bool = True) -> str:
    parts = [str(moment.day)]
    if with_month:
        parts.append(_MONTHS_GENITIVE[moment.month - 1])
    if with_year:
        parts.append(str(moment.year))
    return " ".join(parts)


def date_range(resolved: ResolvedPeriod) -> str:
    start, end = resolved.start_local, resolved.end_local
    zone = getattr(end.tzinfo, "key", None)
    zone_label = "МСК" if zone == "Europe/Moscow" else escape(str(zone or end.tzname()))
    if start.date() == end.date():
        text = _day(end)
    elif (start.year, start.month) == (end.year, end.month):
        text = f"{start.day}–{_day(end)}"
    elif start.year == end.year:
        text = f"{_day(start, with_year=False)} – {_day(end)}"
    else:
        text = f"{_day(start)} – {_day(end)}"
    return f"{text} ({zone_label})"


def _value(text: str) -> str:
    if len(text) > _MAX_VALUE_LENGTH:
        text = text[: _MAX_VALUE_LENGTH - 1] + "…"
    return escape(text)


def country_label(code: str | None) -> str:
    if code is None:
        return "Не определено"
    code = code.upper()
    if len(code) == 2 and code.isascii() and code.isalpha():
        flag = "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in code)
        return f"{flag} {escape(COUNTRY_NAMES.get(code, code))}"
    return escape(code)


def _row_label(row: ShareRow, label: Callable[[str | None], str], other: str) -> str:
    return other if row.is_other else label(row.key)


def _lines(rows: list[ShareRow], label: Callable[[str | None], str]) -> list[str]:
    return [f"{_row_label(row, label, 'Другие')} — {row.visits} ({row.percent}%)" for row in rows]


def _inline(title: str, rows: list[ShareRow], label: Callable[[str | None], str]) -> str:
    parts = [f"{_row_label(row, label, 'другие')} {row.percent}%" for row in rows]
    return f"{title}: {' · '.join(parts)}"


def _header(icon: str, title: str, resolved: ResolvedPeriod) -> list[str]:
    return [f"{icon} <b>{title} · {period_label(resolved.period)}</b>", date_range(resolved), ""]


def _fit(lines: list[str], footer: list[str]) -> str:
    """Join lines within Telegram's limit by dropping whole lines, so no tag is ever cut."""
    lines = list(lines)
    while lines:
        text = "\n".join(lines + footer)
        if len(text) <= MAX_MESSAGE_LENGTH:
            return text
        lines = lines[:-2] + ["…"]
    return "\n".join(footer)[:MAX_MESSAGE_LENGTH]


def format_visitors_report(report: VisitorsReport) -> str:
    lines = _header("📊", "Посещения", report.period)
    if report.visits == 0:
        lines.append(EMPTY_PERIOD_TEXT)
        if report.requests:
            lines.append(f"Заявки: {report.requests}")
        return _fit(lines, [])

    lines += [f"Визиты: {report.visits}", f"Посетители: {report.visitors}*"]
    requests = f"Заявки: {report.requests}"
    if report.conversion is not None:
        conversion = f"{report.conversion * 100:.1f}".replace(".", ",")
        requests += f" · конверсия {conversion}%"
    lines += [requests, "", "<b>Страны</b>", *_lines(report.countries, country_label), ""]

    lines.append(
        _inline("Устройства", report.devices, lambda key: _DEVICE_NAMES.get(key or "", "—"))
    )
    lines.append(_inline("Системы", report.os, lambda key: _value(key or "—")))
    lines.append(_inline("Браузеры", report.browsers, lambda key: _value(key or "—")))
    lines.append(
        _inline("Язык сайта", report.locales, lambda key: key.upper() if key else "не указан")
    )
    if len(report.sites) > 1:
        lines += ["", "<b>Сайты</b>", *_lines(report.sites, lambda key: _value(key or "—"))]
    return _fit(lines, ["", "* уникальные в пределах суток"])


def format_sources_report(report: SourcesReport) -> str:
    lines = _header("🔗", "Источники", report.period)
    if report.visits == 0:
        lines.append(EMPTY_PERIOD_TEXT)
        return _fit(lines, [])

    lines += _lines(report.referrers, lambda key: _value(key) if key else "Прямые заходы")
    if report.utm_campaigns:
        lines += ["", "<b>UTM-кампании</b>"]
        for row in report.utm_campaigns:
            parts = (row.utm_source, row.utm_medium, row.utm_campaign)
            name = " / ".join(_value(part) if part else "—" for part in parts)
            lines.append(f"{name} — {row.visits}")
    return _fit(lines, [])


def format_help() -> str:
    return "\n".join(
        [
            "<b>Статистика лендингов</b>",
            "",
            "/visits [период] — посещения: люди, страны, устройства",
            "/sources [период] — откуда пришли посетители",
            "/help — эта справка",
            "",
            "Период календарный по Москве, текущий день/неделя/месяц включены.",
            "Без периода — 7 дней.",
            f"Дни: 7d, 7 дней (до {PERIOD_LIMITS['day']})",
            f"Недели: 2w, 2 недели (до {PERIOD_LIMITS['week']})",
            f"Месяцы: 3m, 3 месяца (до {PERIOD_LIMITS['month']})",
            "",
            "Примеры: /visits 1d · /visits 2w · /sources 1 месяц",
        ]
    )


def format_command_error(message: str) -> str:
    return escape(message)
