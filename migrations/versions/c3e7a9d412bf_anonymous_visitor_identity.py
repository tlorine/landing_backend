"""Add anonymous browser identity to analytics events.

Revision ID: c3e7a9d412bf
Revises: bf0922bd56ab
Create Date: 2026-10-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e7a9d412bf"
down_revision: str | None = "bf0922bd56ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analytics_events", sa.Column("visitor_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_analytics_visitor",
        "analytics_events",
        ["source_site", "visitor_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_visitor", table_name="analytics_events")
    op.drop_column("analytics_events", "visitor_id")
