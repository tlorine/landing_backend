from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.periods import Period
from app.services.visit_stats import ShareRow, VisitStatsService, percent, referrer_group
from tests.fakes import (
    FakeRequestRepository,
    FakeSessionFactory,
    FakeSiteVisitRepository,
    StoredVisit,
)

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 14, 12, tzinfo=MSK)


def make_service(visits, requests=()) -> VisitStatsService:
    return VisitStatsService(
        session_factory=FakeSessionFactory(),
        visit_repository=FakeSiteVisitRepository(visits),
        request_repository=FakeRequestRepository(list(requests)),
        tz=MSK,
    )


def at(days_ago: int, hour: int = 10) -> datetime:
    return (NOW - timedelta(days=days_ago)).replace(hour=hour)


async def test_visitors_report_aggregates_and_window() -> None:
    visits = [
        *[
            StoredVisit(
                at(0),
                country="AM",
                device_type="mobile",
                os="iOS",
                browser="Safari",
                visitor_hash="a" * 64,
            )
            for _ in range(4)
        ],
        *[StoredVisit(at(1), country="RU", locale="en", visitor_hash="b" * 64) for _ in range(3)],
        StoredVisit(at(2), country=None, visitor_hash="c" * 64),
        # Outside a 7-day window (2026-10-08 00:00 MSK onwards).
        StoredVisit(datetime(2026, 10, 7, 23, 59, tzinfo=MSK), country="DE"),
    ]
    requests = [at(0).astimezone(UTC), datetime(2026, 10, 1, tzinfo=UTC)]
    report = await make_service(visits, requests).visitors_report(Period("day", 7), NOW)

    assert report.period.start_local == datetime(2026, 10, 8, tzinfo=MSK)
    assert (report.visits, report.visitors, report.requests) == (8, 3, 1)
    assert report.conversion == pytest.approx(1 / 3)
    assert report.countries == [
        ShareRow("AM", 4, 50),
        ShareRow("RU", 3, 38),
        ShareRow(None, 1, 13),  # unknown is kept apart and last
    ]
    assert report.devices == [ShareRow("desktop", 4, 50), ShareRow("mobile", 4, 50)]
    assert [row.key for row in report.locales] == ["ru", "en"]
    assert report.sites == [ShareRow("studio-landing", 8, 100)]


async def test_top_n_folds_the_rest_into_other() -> None:
    browsers = ["Chrome"] * 6 + ["Safari"] * 5 + ["A", "B", "C", "D", "E"]
    visits = [StoredVisit(at(0), browser=name) for name in browsers]
    report = await make_service(visits).visitors_report(Period("day", 1), NOW)
    assert [row.key for row in report.browsers[:5]] == ["Chrome", "Safari", "A", "B", "C"]
    assert report.browsers[-1] == ShareRow(None, 2, 13, is_other=True)
    assert sum(row.visits for row in report.browsers) == len(visits)


async def test_countries_top_ten_then_other_then_unknown() -> None:
    codes = [f"{chr(65 + i)}A" for i in range(12)]
    visits = [StoredVisit(at(0), country=code) for code in codes] + [StoredVisit(at(0))]
    report = await make_service(visits).visitors_report(Period("day", 1), NOW)
    assert len(report.countries) == 12
    assert report.countries[10] == ShareRow(None, 2, 15, is_other=True)
    assert report.countries[11] == ShareRow(None, 1, 8)


async def test_empty_period() -> None:
    report = await make_service([]).visitors_report(Period("week", 1), NOW)
    assert (report.visits, report.visitors, report.conversion) == (0, 0, None)
    assert report.countries == []


async def test_sources_report_groups_referrers() -> None:
    hosts = (
        [None] * 5
        + ["t.me"] * 2
        + [
            "web.telegram.org",
            "google.com",
            "google.co.uk",
            "yandex.ru",
            "ya.ru",
            "m.vk.com",
            "partner.example.org",
        ]
    )
    visits = [StoredVisit(at(0), referrer_host=host) for host in hosts]
    visits[0].utm_source, visits[0].utm_medium, visits[0].utm_campaign = "telegram", "post", "oct"
    visits[1].utm_campaign = "only_campaign"
    report = await make_service(visits).sources_report(Period("day", 1), NOW)

    assert report.visits == 14
    assert [(row.key, row.visits) for row in report.referrers] == [
        (None, 5),
        ("Telegram", 3),
        ("Google", 2),
        ("Яндекс", 2),
        ("VK", 1),
        ("partner.example.org", 1),
    ]
    assert {(row.utm_source, row.utm_campaign, row.visits) for row in report.utm_campaigns} == {
        ("telegram", "oct", 1),
        (None, "only_campaign", 1),
    }


@pytest.mark.parametrize(
    ("host", "group"),
    [
        ("telegram.me", "Telegram"),
        ("google.de", "Google"),
        ("yandex.com.tr", "Яндекс"),
        ("vk.com", "VK"),
        ("notgoogle.com", "notgoogle.com"),
        (None, None),
    ],
)
def test_referrer_group(host, group) -> None:
    assert referrer_group(host) == group


def test_percent_rounds_half_up() -> None:
    assert (percent(1, 8), percent(1, 3), percent(0, 0)) == (13, 33, 0)
