"""Give Extraction a real trace_id column.

It was riding inside the `resolved` JSONB, which made the Agent Activity feed a
per-row JSON lookup instead of a join against agent_run.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("extraction", sa.Column("trace_id", pg.UUID(as_uuid=True), nullable=True))

    # Carry over anything already stashed in the JSONB, then drop the key so
    # there is only ever one place to read it from.
    op.execute(
        """
        UPDATE extraction
           SET trace_id = (resolved ->> 'trace_id')::uuid
         WHERE resolved ? 'trace_id'
           AND (resolved ->> 'trace_id') ~
               '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        """
    )
    op.execute("UPDATE extraction SET resolved = resolved - 'trace_id' WHERE resolved ? 'trace_id'")

    op.create_index("ix_extraction_trace_id", "extraction", ["trace_id"])


def downgrade() -> None:
    op.execute(
        """
        UPDATE extraction
           SET resolved = jsonb_set(
                   COALESCE(resolved, '{}'::jsonb), '{trace_id}', to_jsonb(trace_id::text)
               )
         WHERE trace_id IS NOT NULL
        """
    )
    op.drop_index("ix_extraction_trace_id", table_name="extraction")
    op.drop_column("extraction", "trace_id")
