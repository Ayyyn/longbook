"""Watermark table for diff-based overdue alerts.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ledger_watermark",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attributes", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "party_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("party.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("was_overdue", sa.Boolean(), nullable=False),
        sa.Column("days_overdue", sa.Integer(), nullable=True),
        sa.Column("outstanding", sa.Numeric(14, 2), nullable=True),
        sa.Column("last_run_on", sa.Date(), nullable=True),
        sa.UniqueConstraint("tenant_id", "party_id", name="uq_ledger_watermark_party"),
    )
    op.create_index("ix_ledger_watermark_tenant_id", "ledger_watermark", ["tenant_id"])
    op.create_index("ix_ledger_watermark_tenant", "ledger_watermark", ["tenant_id"])
    op.create_index("ix_ledger_watermark_party_id", "ledger_watermark", ["party_id"])


def downgrade() -> None:
    op.drop_table("ledger_watermark")
