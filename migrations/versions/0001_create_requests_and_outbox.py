"""Create service requests and notification outbox tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_requests_outbox"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("budget", sa.String(length=100), nullable=True),
        sa.Column("contact", sa.String(length=254), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_site", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(description) >= 10 AND length(description) <= 5000",
            name="ck_service_requests_description_length",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_service_requests_created_at", "service_requests", ["created_at"], unique=False
    )

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent')",
            name="ck_notification_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_outbox_attempts_nonnegative"),
        sa.ForeignKeyConstraint(["request_id"], ["service_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index(
        "ix_notification_outbox_due",
        "notification_outbox",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_outbox_due", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("ix_service_requests_created_at", table_name="service_requests")
    op.drop_table("service_requests")
