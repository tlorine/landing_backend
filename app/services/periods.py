from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

PeriodUnit = Literal["day", "week", "month"]

# Months are capped by how long visits are kept by default.
PERIOD_LIMITS: dict[PeriodUnit, int] = {"day": 366, "week": 52, "month": 12}


class PeriodError(ValueError):
    """The requested period is outside the supported range."""


@dataclass(frozen=True)
class Period:
    unit: PeriodUnit
    count: int

    def __post_init__(self) -> None:
        limit = PERIOD_LIMITS.get(self.unit)
        if limit is None:
            raise PeriodError(f"Unknown period unit {self.unit!r}.")
        if not 1 <= self.count <= limit:
            raise PeriodError(f"Period count for {self.unit} must be between 1 and {limit}.")


@dataclass(frozen=True)
class ResolvedPeriod:
    """Half-open interval [start, end) in UTC, with the same bounds in the stats time zone."""

    period: Period
    start_utc: datetime
    end_utc: datetime
    start_local: datetime
    end_local: datetime


def shift_months(day: date, months: int) -> date:
    """Move a date by whole months, clamping the day to the target month's length."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    next_month_start = date(year + month // 12, month % 12 + 1, 1)
    last_day = (next_month_start - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def resolve_period(period: Period, now: datetime, tz: ZoneInfo) -> ResolvedPeriod:
    """Calendar period ending at ``now``; the current day, week or month is included."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    end_local = now.astimezone(tz)
    today = end_local.date()
    if period.unit == "day":
        start_day = today - timedelta(days=period.count - 1)
    elif period.unit == "week":
        monday = today - timedelta(days=today.weekday())
        start_day = monday - timedelta(weeks=period.count - 1)
    else:
        start_day = shift_months(today.replace(day=1), -(period.count - 1))

    start_local = datetime.combine(start_day, time.min, tzinfo=tz)
    return ResolvedPeriod(
        period=period,
        start_utc=start_local.astimezone(UTC),
        end_utc=end_local.astimezone(UTC),
        start_local=start_local,
        end_local=end_local,
    )
