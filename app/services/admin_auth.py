import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analytics import AdminLoginAttempt, AdminSession, AdminUser

hasher = PasswordHasher()
_DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
COOKIE = "cobalt_admin"
BOOTSTRAP_COOKIE = "cobalt_csrf"
COOKIE_PATH = "/api/v1/admin"


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AdminAuthService:
    async def authenticate(self, session: AsyncSession, token: str | None) -> AdminSession | None:
        if not token:
            return None
        result = await session.execute(
            select(AdminSession)
            .join(AdminUser, AdminUser.username == AdminSession.username)
            .where(
                AdminSession.token_hash == digest(token),
                AdminSession.expires_at > datetime.now(UTC),
                AdminUser.disabled.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def login(
        self, session: AsyncSession, username: str, password: str, ip: str
    ) -> tuple[tuple[str, AdminSession] | None, str | None]:
        now = datetime.now(UTC)
        # Two independent buckets protect both an account and a network peer. Counters
        # survive restarts, and atomic UPSERTs serialize competing login attempts.
        keys = sorted([digest("user:" + username), digest("ip:" + ip)])
        async with session.begin():
            for key in keys:
                statement = insert(AdminLoginAttempt).values(
                    key=key, window_started_at=now, attempts=1
                )
                old = AdminLoginAttempt.window_started_at < now - timedelta(minutes=15)
                statement = statement.on_conflict_do_update(
                    index_elements=[AdminLoginAttempt.key],
                    set_={
                        "attempts": case((old, 1), else_=AdminLoginAttempt.attempts + 1),
                        "window_started_at": case(
                            (old, now), else_=AdminLoginAttempt.window_started_at
                        ),
                    },
                ).returning(AdminLoginAttempt.attempts)
                count = (await session.execute(statement)).scalar_one()
                if count > 10:
                    # Return normally so the attempted-login counters commit.
                    return None, "rate_limited"
            user = await session.get(AdminUser, username)
            stored_hash = user.password_hash if user else _DUMMY_HASH
            try:
                # Argon2 is CPU/memory intensive: never block the async API event loop.
                from asyncio import to_thread

                valid = await to_thread(hasher.verify, stored_hash, password)
            except VerificationError:
                valid = False
            if not valid or user is None or user.disabled:
                return None, "invalid_credentials"
            if hasher.check_needs_rehash(stored_hash):
                user.password_hash = await to_thread(hasher.hash, password)
            token = secrets.token_urlsafe(32)
            record = AdminSession(
                token_hash=digest(token),
                username=username,
                csrf_token=secrets.token_urlsafe(32),
                expires_at=now + timedelta(hours=settings.admin_session_hours),
            )
            session.add(record)
        return (token, record), None
