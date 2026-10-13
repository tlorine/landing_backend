from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ServiceRequest(Base):
    """A request submitted by a visitor from one of the landing pages."""

    __tablename__ = "service_requests"
    __table_args__ = (
        CheckConstraint(
            "length(description) >= 10 AND length(description) <= 5000",
            name="ck_service_requests_description_length",
        ),
        Index("ix_service_requests_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    budget: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact: Mapped[str] = mapped_column(String(254), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_site: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
