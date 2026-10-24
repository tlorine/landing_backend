"""Seed at 0002, verify at head. Isolated test database only; no destructive operations."""

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionFactory, engine
from app.models.notification_outbox import NotificationOutbox
from app.models.service_request import ServiceRequest
from app.models.site_visit import SiteVisit

REQUEST_ID = UUID("00000000-0000-4000-8000-000000000001")
OUTBOX_ID = UUID("00000000-0000-4000-8000-000000000002")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["seed", "verify"])
    args = parser.parse_args()
    assert settings.app_env == "test" and settings.database_url.endswith("_test")
    try:
        async with SessionFactory() as session, session.begin():
            if args.action == "seed":
                session.add(
                    ServiceRequest(
                        id=REQUEST_ID,
                        name="Migration fixture",
                        contact="fixture@example.test",
                        description="Pre-existing request preserved through analytics migration.",
                        source_site="migration-fixture",
                    )
                )
                session.add(
                    SiteVisit(
                        source_site="migration-fixture",
                        path="/",
                        locale="ru",
                        country="AM",
                        device_type="desktop",
                        os="Linux",
                        browser="Firefox",
                        visitor_hash="f" * 64,
                    )
                )
                await session.flush()
                session.add(NotificationOutbox(id=OUTBOX_ID, request_id=REQUEST_ID))
            else:
                request = await session.get(ServiceRequest, REQUEST_ID)
                assert request and request.contact == "fixture@example.test"
                assert (
                    request.description
                    == "Pre-existing request preserved through analytics migration."
                )
                outbox = await session.get(NotificationOutbox, OUTBOX_ID)
                assert outbox and outbox.request_id == REQUEST_ID and outbox.status == "pending"
                visit = (
                    await session.execute(
                        select(SiteVisit).where(SiteVisit.source_site == "migration-fixture")
                    )
                ).scalar_one()
                assert visit.visitor_hash == "f" * 64 and visit.country == "AM"
                print("Populated 0002 request, outbox and visit preserved.")
    finally:
        await engine.dispose()


asyncio.run(main())
