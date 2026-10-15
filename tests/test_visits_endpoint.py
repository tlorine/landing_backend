import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import visits as visits_endpoint
from app.db.session import get_session
from app.main import app
from app.services.rate_limit import SlidingWindowRateLimiter
from app.services.visits import VisitService
from tests.fakes import FakeSession, FakeSiteVisitRepository

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
IP = "203.0.113.77"


@pytest.fixture
def repository() -> FakeSiteVisitRepository:
    return FakeSiteVisitRepository()


@pytest.fixture
def client(repository: FakeSiteVisitRepository) -> Iterator[TestClient]:
    service = VisitService(repository, tz=visits_endpoint.settings.stats_zone)
    limiter = SlidingWindowRateLimiter(limit=3)

    async def fake_session():
        yield FakeSession()

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[visits_endpoint.get_visit_service] = lambda: service
    app.dependency_overrides[visits_endpoint.get_rate_limiter] = lambda: limiter
    try:
        # No context manager: the lifespan (DB, Telegram workers) is not started.
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def post(
    client: TestClient,
    body: str | bytes,
    content_type: str = "text/plain;charset=UTF-8",
    **headers: str,
):
    return client.post(
        "/api/v1/visits",
        content=body,
        headers={
            "Content-Type": content_type,
            "User-Agent": IPHONE_UA,
            "CF-Connecting-IP": IP,
            **headers,
        },
    )


PAYLOAD = {
    "source_site": "studio-landing",
    "path": "/en?utm_source=x#top",
    "locale": "en",
    "referrer_host": "WWW.Partner.Example.org",
    "utm_source": "telegram",
    "utm_medium": "post",
    "utm_campaign": "launch_oct",
}


@pytest.mark.parametrize("content_type", ["text/plain;charset=UTF-8", "application/json"])
def test_visit_is_recorded(client, repository, content_type) -> None:
    response = post(client, json.dumps(PAYLOAD), content_type, **{"CF-IPCountry": "am"})
    assert response.status_code == 204
    assert response.content == b""
    [visit] = repository.added
    assert visit.source_site == "studio-landing"
    assert visit.path == "/en"
    assert visit.locale == "en"
    assert visit.country == "AM"
    assert visit.device_type == "mobile"
    assert (visit.os, visit.browser) == ("iOS", "Safari")
    assert visit.referrer_host == "partner.example.org"
    assert (visit.utm_source, visit.utm_medium, visit.utm_campaign) == (
        "telegram",
        "post",
        "launch_oct",
    )
    assert len(visit.visitor_hash) == 64


def test_ip_is_not_stored(client, repository) -> None:
    post(client, json.dumps(PAYLOAD))
    [visit] = repository.added
    stored = [str(getattr(visit, column.key)) for column in visit.__table__.columns]
    assert all(IP not in value for value in stored)
    assert all(IPHONE_UA not in value for value in stored)


def test_same_visitor_same_day_has_same_hash(client, repository) -> None:
    post(client, json.dumps(PAYLOAD))
    post(client, json.dumps(PAYLOAD))
    post(client, json.dumps(PAYLOAD), **{"CF-Connecting-IP": "198.51.100.1"})
    first, second, other = (visit.visitor_hash for visit in repository.added)
    assert first == second != other
    assert repository.salt_calls == 1  # today's salt is cached after the first commit


def test_explicit_device_type_wins_over_user_agent(client, repository) -> None:
    post(client, json.dumps({"source_site": "s", "path": "/", "device_type": "tablet"}))
    assert repository.added[0].device_type == "tablet"


@pytest.mark.parametrize(
    ("header", "expected"), [("am", "AM"), ("XX", None), ("T1", None), ("", None), (None, None)]
)
def test_country_header(client, repository, header, expected) -> None:
    headers = {} if header is None else {"CF-IPCountry": header}
    assert post(client, '{"source_site":"s","path":"/"}', **headers).status_code == 204
    assert repository.added[0].country == expected


def test_invalid_json_is_400(client, repository) -> None:
    response = post(client, "{not json")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"
    assert repository.added == []


def test_body_over_2kb_is_413(client, repository) -> None:
    body = json.dumps({"source_site": "s", "path": "/" + "a" * 2100})
    assert post(client, body).status_code == 413
    assert repository.added == []


@pytest.mark.parametrize(
    "payload",
    [
        {"source_site": "s", "path": "no-slash"},
        {"source_site": "s", "path": "/", "device_type": "phone"},
        {"source_site": "s", "path": "/", "locale": "de"},
        {"source_site": "", "path": "/"},
        {"path": "/"},
        {"source_site": "s\x00", "path": "/"},
        {"source_site": "s", "path": "/", "utm_source": "x" * 101},
        ["not", "an", "object"],
    ],
)
def test_validation_errors_are_422(client, repository, payload) -> None:
    response = post(client, json.dumps(payload))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert repository.added == []


def test_invalid_referrer_becomes_null(client, repository) -> None:
    post(client, json.dumps({"source_site": "s", "path": "/", "referrer_host": "bad host/"}))
    assert repository.added[0].referrer_host is None


@pytest.mark.parametrize("user_agent", ["", "Mozilla/5.0 (compatible; Googlebot/2.1)", "curl/8.7"])
def test_bots_and_empty_user_agent_are_skipped(client, repository, user_agent) -> None:
    response = post(client, json.dumps(PAYLOAD), **{"User-Agent": user_agent})
    assert response.status_code == 204
    assert repository.added == []


def test_rate_limit_is_429(client, repository) -> None:
    statuses = [post(client, json.dumps(PAYLOAD)).status_code for _ in range(4)]
    assert statuses == [204, 204, 204, 429]
    assert len(repository.added) == 3
    # Another visitor is not affected.
    assert (
        post(client, json.dumps(PAYLOAD), **{"CF-Connecting-IP": "198.51.100.2"}).status_code == 204
    )


def test_responses_do_not_leak_ip_or_user_agent(client) -> None:
    for body in ("{bad", json.dumps({"path": "x"})):
        text = post(client, body).text
        assert IP not in text and IPHONE_UA not in text


def test_rate_limiter_window_slides() -> None:
    now = [0.0]
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("k") and limiter.allow("k") and not limiter.allow("k")
    now[0] = 60.5
    assert limiter.allow("k")
