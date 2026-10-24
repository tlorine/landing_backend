"""Management commands. Passwords are read interactively, never from argv or logs."""

import argparse
import asyncio
import getpass
import re
from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.core.config import settings
from app.db.session import SessionFactory, engine
from app.models.analytics import AdminSession, AdminUser, AnalyticsCoverage
from app.services.admin_auth import hasher


async def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("admin-set-password")
    admin.add_argument("username")
    coverage = sub.add_parser("analytics-coverage")
    coverage.add_argument("action", choices=["start", "stop"])
    coverage.add_argument("source_site")
    args = parser.parse_args()
    try:
        async with SessionFactory() as session, session.begin():
            if args.command == "admin-set-password":
                if not re.fullmatch(r"[a-zA-Z0-9_.@-]{1,100}", args.username):
                    parser.error("Invalid username")
                password = getpass.getpass("New password (minimum 12 characters): ")
                if len(password) < 12 or len(password) > 1024:
                    parser.error("Password must contain 12–1024 characters")
                if password != getpass.getpass("Repeat password: "):
                    parser.error("Passwords differ")
                user = await session.get(AdminUser, args.username)
                if user is None:
                    user = AdminUser(username=args.username)
                    session.add(user)
                user.password_hash = hasher.hash(password)
                user.disabled = False
                await session.execute(
                    delete(AdminSession).where(AdminSession.username == args.username)
                )
                print("Admin password saved; existing sessions revoked.")
            else:
                if args.source_site not in settings.analytics_sites:
                    parser.error("Site is not configured")
                # Serialize coverage administration per site, including empty table case.
                from sqlalchemy import text

                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:site))"),
                    {"site": args.source_site},
                )
                active = (
                    await session.execute(
                        select(AnalyticsCoverage).where(
                            AnalyticsCoverage.source_site == args.source_site,
                            AnalyticsCoverage.ended_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if args.action == "start":
                    if active:
                        parser.error("Coverage already active; stop before changing mode")
                    session.add(
                        AnalyticsCoverage(
                            source_site=args.source_site,
                            started_at=datetime.now(UTC),
                            sessions_enabled=settings.analytics_sessions_enabled,
                        )
                    )
                elif active:
                    active.ended_at = datetime.now(UTC)
                print("Coverage updated.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
