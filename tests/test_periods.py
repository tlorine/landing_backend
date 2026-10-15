from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.periods import Period, PeriodError, resolve_period, shift_months

MSK = ZoneInfo("Europe/Moscow")


def msk(*args: int) -> datetime:
    return datetime(*args, tzinfo=MSK)


def test_one_day_at_2359_starts_today() -> None:
    resolved = resolve_period(Period("day", 1), msk(2026, 10, 14, 23, 59), MSK)
    assert resolved.start_local == msk(2026, 10, 14)
    assert resolved.start_utc == datetime(2026, 10, 13, 21, tzinfo=UTC)
    assert resolved.end_utc == datetime(2026, 10, 14, 20, 59, tzinfo=UTC)


def test_one_day_at_0001_starts_at_local_midnight_not_utc() -> None:
    # 00:01 MSK is still the previous day in UTC.
    resolved = resolve_period(Period("day", 1), msk(2026, 10, 15, 0, 1), MSK)
    assert resolved.start_local == msk(2026, 10, 15)
    assert resolved.end_utc == datetime(2026, 10, 14, 21, 1, tzinfo=UTC)


def test_seven_days_include_today() -> None:
    resolved = resolve_period(Period("day", 7), msk(2026, 10, 14, 12), MSK)
    assert resolved.start_local == msk(2026, 10, 8)


def test_week_starts_on_monday() -> None:
    # 2026-10-14 is a Wednesday.
    resolved = resolve_period(Period("week", 1), msk(2026, 10, 14, 12), MSK)
    assert resolved.start_local == msk(2026, 10, 12)


def test_week_on_monday_morning() -> None:
    resolved = resolve_period(Period("week", 2), msk(2026, 10, 12, 0, 1), MSK)
    assert resolved.start_local == msk(2026, 10, 5)


def test_month_on_first_day() -> None:
    resolved = resolve_period(Period("month", 1), msk(2026, 10, 1, 0, 1), MSK)
    assert resolved.start_local == msk(2026, 10, 1)


def test_months_cross_year_boundary() -> None:
    resolved = resolve_period(Period("month", 3), msk(2026, 1, 20, 10), MSK)
    assert resolved.start_local == msk(2025, 11, 1)


def test_weeks_cross_year_boundary() -> None:
    # 2026-01-01 is a Thursday; its week starts on 2025-12-29.
    resolved = resolve_period(Period("week", 1), msk(2026, 1, 1, 10), MSK)
    assert resolved.start_local == msk(2025, 12, 29)


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_period(Period("day", 1), datetime(2026, 1, 1), MSK)


@pytest.mark.parametrize(
    ("unit", "count"),
    [("day", 0), ("day", 367), ("week", 53), ("month", 13), ("month", -1), ("year", 1)],
)
def test_limits(unit: str, count: int) -> None:
    with pytest.raises(PeriodError):
        Period(unit, count)  # type: ignore[arg-type]


@pytest.mark.parametrize(("unit", "count"), [("day", 366), ("week", 52), ("month", 12)])
def test_upper_limits_are_allowed(unit: str, count: int) -> None:
    assert Period(unit, count).count == count  # type: ignore[arg-type]


def test_shift_months_clamps_day() -> None:
    assert shift_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert shift_months(date(2026, 10, 15), -12) == date(2025, 10, 15)
