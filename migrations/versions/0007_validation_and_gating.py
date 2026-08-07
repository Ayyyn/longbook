"""Validation results and pending fields on an extraction.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extraction", sa.Column("validations", pg.JSONB(), nullable=True))
    op.add_column("extraction", sa.Column("pending_fields", pg.JSONB(), nullable=True))

    # Partially-committed rows carry `attributes->pending_fields`, and the
    # ledger has to skip them. Indexed because every outstanding and ageing
    # query filters on it.
    for table in ("payment", "invoice", "order"):
        op.create_index(
            f"ix_{table}_pending_fields",
            table,
            [sa.text("(attributes -> 'pending_fields')")],
            postgresql_using="gin",
        )


def downgrade() -> None:
    for table in ("payment", "invoice", "order"):
        op.drop_index(f"ix_{table}_pending_fields", table_name=table)
    op.drop_column("extraction", "pending_fields")
    op.drop_column("extraction", "validations")
