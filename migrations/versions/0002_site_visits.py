"""Create site visits and daily visitor salts tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_site_visits"
down_revision: str | None = "0001_requests_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_visits",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source_site", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=True),
        sa.Column("country", sa.CHAR(length=2), nullable=True),
        sa.Column("device_type", sa.String(length=16), nullable=False),
        sa.Column("os", sa.String(length=32), nullable=False),
        sa.Column("browser", sa.String(length=32), nullable=False),
        sa.Column("referrer_host", sa.String(length=255), nullable=True),
        sa.Column("utm_source", sa.String(length=100), nullable=True),
        sa.Column("utm_medium", sa.String(length=100), nullable=True),
        sa.Column("utm_campaign", sa.String(length=100), nullable=True),
        sa.Column("visitor_hash", sa.CHAR(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_visits_occurred_at", "site_visits", ["occurred_at"], unique=False)
    op.create_index(
        "ix_site_visits_site_occurred_at",
        "site_visits",
        ["source_site", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "visit_salts",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("salt", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("day"),
    )


def downgrade() -> None:
    op.drop_table("visit_salts")
    op.drop_index("ix_site_visits_site_occurred_at", table_name="site_visits")
    op.drop_index("ix_site_visits_occurred_at", table_name="site_visits")
    op.drop_table("site_visits")
