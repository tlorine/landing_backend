from datetime import UTC, date, datetime

import pytest
from starlette.requests import Request

from app.core.config import settings
from app.services.analytics_reports import ReportFilters
from app.services.client_context import client_context


def test_arbitrary_range_half_open_dst_and_limits():
    filters = ReportFilters.resolve(
        "studio-landing", date(2026, 3, 29), date(2026, 3, 30), "Europe/Berlin"
    )
    start, end = filters.bounds()
    assert (end - start).total_seconds() == 23 * 3600
    assert start == datetime(2026, 3, 28, 23, tzinfo=UTC)
    with pytest.raises(ValueError):
        ReportFilters.resolve("studio-landing", date(2020, 1, 1), date(2026, 1, 1), "UTC")
    with pytest.raises(ValueError):
        ReportFilters.resolve("studio-landing", date(2026, 1, 2), date(2026, 1, 1), "UTC")
    with pytest.raises(ValueError):
        ReportFilters.resolve("unknown", None, None, "UTC")


def test_trusted_context_rejects_forged_headers(monkeypatch):
    scope = {
        "type": "http",
        "headers": [(b"cf-connecting-ip", b"203.0.113.44"), (b"cf-ipcountry", b"AM")],
        "client": ("192.0.2.1", 1000),
    }
    monkeypatch.setattr(settings, "trust_cloudflare_headers", True)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", ["127.0.0.0/8"])
    assert client_context(Request(scope)).country is None
    scope["client"] = ("127.0.0.1", 1000)
    assert client_context(Request(scope)).country == "AM"
    monkeypatch.setattr(settings, "trust_cloudflare_headers", False)
    assert client_context(Request(scope)).ip == "127.0.0.1"
