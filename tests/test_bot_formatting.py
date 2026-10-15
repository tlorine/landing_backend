from datetime import datetime
from zoneinfo import ZoneInfo

from app.bot.formatting import (
    EMPTY_PERIOD_TEXT,
    MAX_MESSAGE_LENGTH,
    country_label,
    date_range,
    format_help,
    format_sources_report,
    format_visitors_report,
    period_label,
)
from app.repositories.site_visits import UtmCampaignRow
from app.services.periods import Period, resolve_period
from app.services.visit_stats import ShareRow, SourcesReport, VisitorsReport

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 14, 15, tzinfo=MSK)
WEEK = resolve_period(Period("day", 7), NOW, MSK)


def visitors_report(**overrides) -> VisitorsReport:
    data = dict(
        period=WEEK,
        visits=412,
        visitors=287,
        requests=6,
        conversion=6 / 287,
        countries=[
            ShareRow("AM", 168, 41),
            ShareRow("RU", 136, 33),
            ShareRow(None, 71, 17, is_other=True),
            ShareRow(None, 4, 1),
        ],
        devices=[ShareRow("mobile", 251, 61), ShareRow("desktop", 144, 35)],
        os=[ShareRow("iOS", 140, 34), ShareRow(None, 12, 3, is_other=True)],
        browsers=[ShareRow("Chrome", 169, 41)],
        locales=[ShareRow("ru", 321, 78), ShareRow("en", 91, 22)],
        sites=[ShareRow("studio-landing", 412, 100)],
    )
    data.update(overrides)
    return VisitorsReport(**data)


def test_visitors_report_layout() -> None:
    text = format_visitors_report(visitors_report())
    assert text.startswith("📊 <b>Посещения · 7 дней</b>\n8–14 октября 2026 (МСК)")
    assert "Посетители: 287*" in text
    assert "Заявки: 6 · конверсия 2,1%" in text
    assert "🇦🇲 Армения — 168 (41%)" in text
    assert "Другие — 71 (17%)\nНе определено — 4 (1%)" in text
    assert "Устройства: телефон 61% · компьютер 35%" in text
    assert "Системы: iOS 34% · другие 3%" in text
    assert "Язык сайта: RU 78% · EN 22%" in text
    assert "Сайты" not in text  # only one site
    assert text.endswith("* уникальные в пределах суток")


def test_html_is_escaped() -> None:
    report = SourcesReport(
        period=WEEK,
        visits=3,
        referrers=[ShareRow("<b>evil</b>.com", 2, 67), ShareRow(None, 1, 33)],
        utm_campaigns=[UtmCampaignRow("<script>", None, "a&b", 2)],
    )
    text = format_sources_report(report)
    assert "&lt;b&gt;evil&lt;/b&gt;.com — 2 (67%)" in text
    assert "Прямые заходы — 1 (33%)" in text
    assert "&lt;script&gt; / — / a&amp;b — 2" in text
    assert "<script>" not in text


def test_long_report_fits_telegram_limit_without_cutting_tags() -> None:
    long_values = [ShareRow("x" * 255 + str(i), 1, 1) for i in range(200)]
    report = visitors_report(sites=long_values, countries=long_values)
    text = format_visitors_report(report)
    assert len(text) <= MAX_MESSAGE_LENGTH
    assert text.count("<b>") == text.count("</b>")
    sources = SourcesReport(
        period=WEEK,
        visits=10,
        referrers=long_values,
        utm_campaigns=[UtmCampaignRow("s" * 100, "m" * 100, "c" * 100, 1)] * 200,
    )
    text = format_sources_report(sources)
    assert len(text) <= MAX_MESSAGE_LENGTH
    assert text.count("<b>") == text.count("</b>")


def test_empty_period() -> None:
    text = format_visitors_report(visitors_report(visits=0, visitors=0, requests=0))
    assert text.endswith(EMPTY_PERIOD_TEXT)
    sources = SourcesReport(period=WEEK, visits=0, referrers=[], utm_campaigns=[])
    assert format_sources_report(sources).endswith(EMPTY_PERIOD_TEXT)


def test_country_labels() -> None:
    assert country_label("RU") == "🇷🇺 Россия"
    assert country_label("BR") == "🇧🇷 BR"
    assert country_label(None) == "Не определено"


def test_period_labels_and_ranges() -> None:
    assert [period_label(Period("day", n)) for n in (1, 2, 5, 11, 21, 22)] == [
        "1 день",
        "2 дня",
        "5 дней",
        "11 дней",
        "21 день",
        "22 дня",
    ]
    assert period_label(Period("month", 3)) == "3 месяца"
    assert date_range(resolve_period(Period("day", 1), NOW, MSK)) == "14 октября 2026 (МСК)"
    assert date_range(resolve_period(Period("month", 2), NOW, MSK)) == (
        "1 сентября – 14 октября 2026 (МСК)"
    )
    january = datetime(2026, 1, 5, tzinfo=MSK)
    assert date_range(resolve_period(Period("month", 2), january, MSK)) == (
        "1 декабря 2025 – 5 января 2026 (МСК)"
    )


def test_help_lists_commands() -> None:
    text = format_help()
    assert "/visits" in text and "/sources" in text and "7d" in text
