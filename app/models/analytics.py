"""Analytics facts and revocable admin sessions; no raw IP or User-Agent."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_site_time", "source_site", "occurred_at"),
        Index("ix_analytics_case_time", "source_site", "case_id", "occurred_at"),
        Index("ix_analytics_session", "source_site", "session_id"),
        Index("ix_analytics_visitor", "source_site", "visitor_id", "occurred_at"),
        Index("ix_analytics_page", "source_site", "page_view_id"),
        Index("ix_analytics_navigation", "source_site", "navigation_id"),
        CheckConstraint("event_type IN ('page_view','case_open','case_outbound_click')"),
    )
    source_site: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    session_id: Mapped[UUID | None] = mapped_column(Uuid)
    visitor_id: Mapped[UUID | None] = mapped_column(Uuid)
    page_view_id: Mapped[UUID] = mapped_column(Uuid)
    navigation_id: Mapped[UUID | None] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(512))
    locale: Mapped[str] = mapped_column(String(8))
    device_type: Mapped[str] = mapped_column(String(16))
    case_id: Mapped[str | None] = mapped_column(String(100))
    link_id: Mapped[str | None] = mapped_column(String(100))
    placement: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(2))


class AnalyticsSession(Base):
    __tablename__ = "analytics_sessions"
    source_site: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_event_id: Mapped[UUID] = mapped_column(Uuid)
    entry_locale: Mapped[str] = mapped_column(String(8))
    country: Mapped[str | None] = mapped_column(String(2))
    source_type: Mapped[str] = mapped_column(String(32))
    source_value: Mapped[str | None] = mapped_column(String(255))
    utm_medium: Mapped[str | None] = mapped_column(String(100))
    utm_campaign: Mapped[str | None] = mapped_column(String(100))


class AnalyticsCoverage(Base):
    __tablename__ = "analytics_coverage"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_site: Mapped[str] = mapped_column(String(255), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sessions_enabled: Mapped[bool] = mapped_column(Boolean)


class AdminUser(Base):
    __tablename__ = "admin_users"
    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(
        String(100), ForeignKey("admin_users.username", ondelete="CASCADE"), index=True
    )
    csrf_token: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AdminLoginAttempt(Base):
    __tablename__ = "admin_login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)
