"""Conversation windows as the unit of extraction.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_window",
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
        sa.Column("thread_key", sa.String(200), nullable=True),
        sa.Column("window_key", sa.String(64), nullable=False),
        # Not a foreign key on purpose: interaction.window_id already points
        # the other way, and both would make the tables mutually dependent.
        sa.Column("anchor_interaction_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("extracted_hash", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id", "window_key", name="uq_extraction_window_key"),
    )
    op.create_index("ix_extraction_window_tenant_id", "extraction_window", ["tenant_id"])
    op.create_index("ix_extraction_window_tenant", "extraction_window", ["tenant_id"])
    op.create_index("ix_extraction_window_thread_key", "extraction_window", ["thread_key"])
    op.create_index("ix_extraction_window_started_at", "extraction_window", ["started_at"])
    op.create_index("ix_extraction_window_outcome", "extraction_window", ["outcome"])

    op.add_column(
        "interaction",
        sa.Column(
            "window_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("extraction_window.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_interaction_window_id", "interaction", ["window_id"])

    op.add_column(
        "extraction",
        sa.Column(
            "window_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("extraction_window.id"),
            nullable=True,
        ),
    )
    op.add_column("extraction", sa.Column("source_message_ids", pg.JSONB(), nullable=True))
    op.create_index("ix_extraction_window_id", "extraction", ["window_id"])

    # The old per-message watermark. Windows carry progress now, and leaving
    # the key behind would let a re-run skip messages whose window changed.
    op.execute("UPDATE interaction SET attributes = attributes - 'outcome'")


def downgrade() -> None:
    op.drop_index("ix_extraction_window_id", table_name="extraction")
    op.drop_column("extraction", "source_message_ids")
    op.drop_column("extraction", "window_id")
    op.drop_index("ix_interaction_window_id", table_name="interaction")
    op.drop_column("interaction", "window_id")
    op.drop_table("extraction_window")
