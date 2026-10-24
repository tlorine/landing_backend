"""Real PostgreSQL tests. Opt-in, isolated TEST_DATABASE_URL; never use app DATABASE_URL."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import get_session
from app.main import app
from app.models.analytics import AdminUser, AnalyticsCoverage, AnalyticsEvent, AnalyticsSession
from app.models.site_visit import SiteVisit
from app.services.admin_auth import hasher

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires isolated TEST_DATABASE_URL")
ORIGIN = "http://localhost:5173"
UA = "Mozilla/5.0 AppleWebKit/537.36 Chrome/130.0 Safari/537.36"


@pytest_asyncio.fixture
async def database(monkeypatch):
    parsed_url = make_url(URL)
    if (
        os.environ.get("APP_ENV") != "test"
        or not parsed_url.database
        or not parsed_url.database.endswith("_test")
        or parsed_url.drivername != "postgresql+asyncpg"
        or parsed_url.host not in ("localhost", "127.0.0.1", "postgres")
    ):
        raise RuntimeError("Only local explicitly isolated *_test PostgreSQL databases are allowed")
    engine = create_async_engine(URL, poolclass=NullPool, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # Independent developer/CI invocations may share the named isolated DB.
    # Serialize destructive fixture setup through a session-level PG advisory lock.
    lock_connection = await engine.connect()
    await lock_connection.execute(text("SELECT pg_advisory_lock(862009201)"))
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE analytics_events, analytics_sessions, analytics_coverage, "
                "admin_sessions, admin_users, admin_login_attempts, site_visits, "
                "visit_salts RESTART IDENTITY CASCADE"
            )
        )
    for key, value in {
        "analytics_enabled": True,
        "analytics_sessions_enabled": True,
        "admin_enabled": True,
        "admin_origins": [ORIGIN],
        "cors_origins": [ORIGIN],
        "trust_cloudflare_headers": False,
    }.items():
        monkeypatch.setattr(settings, key, value)

    async def dependency():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = dependency
    async with factory() as session, session.begin():
        session.add(AdminUser(username="tester", password_hash=hasher.hash("valid-password-123")))
        session.add(
            AnalyticsCoverage(
                source_site="studio-landing",
                started_at=datetime.now(UTC) - timedelta(days=40),
                sessions_enabled=True,
            )
        )
    try:
        yield factory
    finally:
        app.dependency_overrides.clear()
        await lock_connection.execute(text("SELECT pg_advisory_unlock(862009201)"))
        await lock_connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(database):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost:5173",
        headers={"Origin": ORIGIN, "User-Agent": UA},
    ) as client:
        yield client


async def login(client):
    token = (await client.get("/api/v1/admin/auth/csrf")).json()["csrf_token"]
    result = await client.post(
        "/api/v1/admin/auth/login",
        headers={"X-CSRF-Token": token},
        json={"username": "tester", "password": "valid-password-123"},
    )
    assert result.status_code == 200, result.text
    return result.json()["csrf_token"]


def event(
    kind="page_view",
    case_id=None,
    page_view_id=None,
    session_id=None,
    navigation_id=None,
    at=None,
    sequence=1,
):
    now = at or datetime.now(UTC) - timedelta(seconds=5)
    result = {
        "event_id": str(uuid4()),
        "event_type": kind,
        "occurred_at": now.isoformat(),
        "source_site": "studio-landing",
        "page_view_id": str(page_view_id or uuid4()),
        "session_id": str(session_id or uuid4()),
        "navigation_id": str(navigation_id) if navigation_id else None,
        "sequence": sequence,
        "path": f"/cases/{case_id}" if case_id and kind != "case_open" else "/",
        "locale": "ru",
        "device_type": "desktop",
        "case_id": case_id,
        "placement": None,
        "link_id": None,
        "entry_context": None,
    }
    if kind == "case_open":
        result["placement"] = "home_cases"
    if kind == "case_outbound_click":
        result.update(placement="case_project", link_id="project_primary")
    return result


async def send(client, events):
    return await client.post(
        "/api/v1/analytics/events", json={"schema_version": 1, "events": events}
    )


async def test_concurrent_duplicate_projection_and_conflict(client, database):
    payload = event()
    responses = await asyncio.gather(*(send(client, [payload]) for _ in range(8)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert sum(r.json()["accepted"] for r in responses) == 1
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(AnalyticsEvent)) == 1
        assert await session.scalar(select(func.count()).select_from(SiteVisit)) == 1
    altered = dict(payload, device_type="mobile")
    response = await send(client, [event(), altered])
    assert response.status_code == 409
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(AnalyticsEvent)) == 1
        assert await session.scalar(select(func.count()).select_from(SiteVisit)) == 1


async def test_out_of_order_navigation_and_real_report(client, database):
    await login(client)
    now = datetime.now(UTC) - timedelta(seconds=10)
    sid, target_sid, page, nav = uuid4(), uuid4(), uuid4(), uuid4()
    opened = event("case_open", "airena", session_id=sid, navigation_id=nav, at=now)
    viewed = event(
        case_id="airena",
        session_id=target_sid,
        page_view_id=page,
        navigation_id=nav,
        at=now + timedelta(seconds=1),
    )
    outbound = event(
        "case_outbound_click",
        "airena",
        session_id=target_sid,
        page_view_id=page,
        at=now + timedelta(seconds=2),
        sequence=2,
    )
    assert (await send(client, [outbound])).status_code == 200
    assert (await send(client, [viewed, opened])).status_code == 200
    response = await client.get("/api/v1/admin/analytics/cases/airena", params={"timezone": "UTC"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["case"]["conversion"] == 1
    assert data["case"]["case_views"] == 1
    assert data["funnel"] == {"opens": 1, "views": 1, "outbound": 1}
    assert data["links"] == [{"link_id": "project_primary", "count": 1}]
    assert response.headers["cache-control"] == "no-store"
    assert data["countries"] == [{"key": None, "count": 2, "share": 1.0}]


async def test_session_attribution_and_concurrent_mixed_batches(client, database):
    sid1, sid2 = uuid4(), uuid4()
    now = datetime.now(UTC) - timedelta(seconds=20)
    earliest = event(session_id=sid1, at=now)
    earliest["entry_context"] = {
        "entry_page_view_id": earliest["page_view_id"],
        "started_at": now.isoformat(),
        "path": "/",
        "utm_source": "launch",
    }
    later = event(session_id=sid1, at=now + timedelta(seconds=2))
    other = event(session_id=sid2, at=now)
    results = await asyncio.gather(
        send(client, [later, other]), send(client, [earliest, event(session_id=sid2)])
    )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    async with database() as session:
        row = await session.get(AnalyticsSession, ("studio-landing", sid1))
        assert row.source_value == "launch"
        assert row.started_at == now


async def test_auth_csrf_disabled_revocation_and_error_envelope(client, database):
    assert (await client.get("/api/v1/admin/analytics/overview")).status_code == 401
    denied = await client.post(
        "/api/v1/admin/auth/login", json={"username": "tester", "password": "x"}
    )
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "csrf_failed"
    csrf = await login(client)
    me = await client.get("/api/v1/admin/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "tester"
    assert (await client.post("/api/v1/admin/auth/logout")).status_code == 403
    async with database() as session, session.begin():
        user = await session.get(AdminUser, "tester")
        user.disabled = True
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401
    async with database() as session, session.begin():
        user = await session.get(AdminUser, "tester")
        user.disabled = False
    assert (
        await client.post("/api/v1/admin/auth/logout", headers={"X-CSRF-Token": csrf})
    ).status_code == 204
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401


async def test_unknown_geo_invalid_batch_and_no_outbound(client, database):
    good = event(case_id="neurobit")
    response = await client.post(
        "/api/v1/analytics/events",
        json={"schema_version": 1, "events": [good]},
        headers={"CF-IPCountry": "RU", "CF-Connecting-IP": "203.0.113.2"},
    )
    assert response.status_code == 200
    async with database() as session:
        assert (await session.scalars(select(AnalyticsEvent))).one().country is None
    invalid = event("case_outbound_click", "neurobit")
    assert (await send(client, [event(), invalid])).status_code == 422
    await login(client)
    response = await client.get("/api/v1/admin/analytics/cases/neurobit")
    assert response.status_code == 200, response.text
    assert response.json()["case"]["conversion"] is None
    assert response.json()["case"]["has_outbound_link"] is False
    invalid_query = await client.get("/api/v1/admin/analytics/overview?timezone=Wrong/Zone")
    assert invalid_query.status_code == 422 and "error" in invalid_query.json()


async def test_session_conversion_ignores_wrong_session_and_duplicate_clicks(client, database):
    await login(client)
    page, sid = uuid4(), uuid4()
    now = datetime.now(UTC) - timedelta(seconds=10)
    view = event(case_id="airena", page_view_id=page, session_id=sid, at=now)
    wrong = event(
        "case_outbound_click",
        "airena",
        page_view_id=page,
        session_id=uuid4(),
        at=now + timedelta(seconds=1),
        sequence=2,
    )
    assert (await send(client, [view, wrong])).status_code == 200
    report = (await client.get("/api/v1/admin/analytics/cases/airena")).json()
    assert report["case"]["conversion"] == 0
    correct = event(
        "case_outbound_click",
        "airena",
        page_view_id=page,
        session_id=sid,
        at=now + timedelta(seconds=2),
        sequence=3,
    )
    assert (await send(client, [correct, correct])).status_code == 200
    report = (await client.get("/api/v1/admin/analytics/cases/airena")).json()
    assert report["case"]["conversion"] == 1
    assert report["case"]["outbound_clicks"] == 2


async def test_body_media_origin_and_sessions_disabled(client, database, monkeypatch):
    assert (
        await client.post(
            "/api/v1/analytics/events", content="x" * 32769, headers={"Content-Type": "text/plain"}
        )
    ).status_code == 413
    assert (
        await client.post(
            "/api/v1/analytics/events", content="{", headers={"Content-Type": "text/plain"}
        )
    ).status_code == 400
    assert (await client.post("/api/v1/analytics/events", content="x")).status_code == 415
    assert (
        await client.post(
            "/api/v1/analytics/events",
            json={"schema_version": 1, "events": [event()]},
            headers={"Origin": "https://forged.invalid"},
        )
    ).status_code == 403
    monkeypatch.setattr(settings, "analytics_sessions_enabled", False)
    from sqlalchemy import update

    async with database() as session, session.begin():
        await session.execute(update(AnalyticsCoverage).values(sessions_enabled=False))
    assert (await send(client, [event()])).status_code == 422
    payload = event()
    payload["session_id"] = None
    assert (await send(client, [payload])).status_code == 200
    await login(client)
    report = (await client.get("/api/v1/admin/analytics/overview")).json()
    assert report["summary"]["sessions"]["value"] is None
    assert report["summary"]["page_views"]["value"] == 1


async def test_login_throttle_persists(client, database):
    token = (await client.get("/api/v1/admin/auth/csrf")).json()["csrf_token"]
    statuses = []
    for _ in range(11):
        result = await client.post(
            "/api/v1/admin/auth/login",
            headers={"X-CSRF-Token": token},
            json={"username": "tester", "password": "wrong"},
        )
        statuses.append(result.status_code)
    assert statuses == [401] * 10 + [429]
    assert result.headers["retry-after"] == "900"
    # The restriction is persisted, not only a process-local counter.
    from app.models.analytics import AdminLoginAttempt

    async with database() as session:
        assert await session.scalar(select(func.max(AdminLoginAttempt.attempts))) >= 11


async def test_retention_preserves_referenced_sessions_and_coverage(client, database):
    payload = event()
    assert (await send(client, [payload])).status_code == 200
    from app.services.analytics_retention import AnalyticsRetentionWorker

    worker = AnalyticsRetentionWorker(database, settings)
    await worker.purge_once()
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(AnalyticsEvent)) == 1
        assert await session.scalar(select(func.count()).select_from(AnalyticsSession)) == 1
        assert await session.scalar(select(func.count()).select_from(AnalyticsCoverage)) == 1
    await worker.purge_once(datetime.now(UTC) + timedelta(days=500))
    async with database() as session:
        assert await session.scalar(select(func.count()).select_from(AnalyticsEvent)) == 0
        assert await session.scalar(select(func.count()).select_from(AnalyticsSession)) == 0
        assert await session.scalar(select(func.count()).select_from(AnalyticsCoverage)) == 1


async def test_distinct_sessions_across_days_not_sum_of_daily(client, database):
    # Endpoint accepts only 24h old events; service inserts historical fixture.
    from app.schemas.analytics import AnalyticsBatch
    from app.services.analytics_ingestion import AnalyticsIngestionService
    from app.services.client_context import ClientContext

    sid = uuid4()
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    events = [event(session_id=sid, at=yesterday), event(session_id=sid, at=now)]
    async with database() as session:
        await AnalyticsIngestionService().record(
            session,
            AnalyticsBatch(schema_version=1, events=events),
            ClientContext("127.0.0.1", None),
            UA,
        )
    await login(client)
    data = (await client.get("/api/v1/admin/analytics/overview", params={"timezone": "UTC"})).json()
    assert data["summary"]["sessions"]["value"] == 1
    assert sum(p["sessions"] for p in data["daily_series"]) == 2


async def test_admin_expiry_and_partial_coverage(client, database):
    await login(client)
    from sqlalchemy import update

    from app.models.analytics import AdminSession

    async with database() as session, session.begin():
        await session.execute(
            update(AdminSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (await client.get("/api/v1/admin/auth/me")).status_code == 401
    await login(client)
    async with database() as session, session.begin():
        await session.execute(
            update(AnalyticsCoverage).values(started_at=datetime.now(UTC) - timedelta(days=2))
        )
    report = (await client.get("/api/v1/admin/analytics/overview")).json()
    assert report["coverage"]["partial"] is True
    assert report["coverage"]["previous_partial"] is True
    assert report["summary"]["page_views"]["previous_value"] is None
    assert report["summary"]["page_views"]["delta_percent"] is None


async def test_historical_sessions_visible_after_ingestion_mode_disabled(
    client, database, monkeypatch
):
    payload = event()
    assert (await send(client, [payload])).status_code == 200
    monkeypatch.setattr(settings, "analytics_sessions_enabled", False)
    await login(client)
    result = await client.get("/api/v1/admin/analytics/overview")
    assert result.status_code == 200, result.text
    assert result.json()["summary"]["sessions"]["value"] == 1
    capabilities = (await client.get("/api/v1/admin/analytics/capabilities")).json()
    assert capabilities["session_tracking_enabled"] is False
