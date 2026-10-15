from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Date,
    DateTime,
    Identity,
    Index,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SiteVisit(Base):
    """An anonymous page load; the visitor's IP address is never stored."""

    __tablename__ = "site_visits"
    __table_args__ = (
        Index("ix_site_visits_occurred_at", "occurred_at"),
        Index("ix_site_visits_site_occurred_at", "source_site", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_site: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    country: Mapped[str | None] = mapped_column(CHAR(2), nullable=True)
    device_type: Mapped[str] = mapped_column(String(16), nullable=False)
    os: Mapped[str] = mapped_column(String(32), nullable=False)
    browser: Mapped[str] = mapped_column(String(32), nullable=False)
    referrer_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visitor_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)


class VisitSalt(Base):
    """Daily random salt for visitor hashes; deleting it unlinks hashes from IP addresses."""

    __tablename__ = "visit_salts"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    salt: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
