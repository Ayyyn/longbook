"""Per-message dedupe hash, and a ledger of what was imported.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Hashing whole files would only catch the case where someone uploads the
    # identical export twice. The case that actually happens is re-exporting
    # the same chat a month later: the file differs, but nine tenths of the
    # messages are ones we already hold. Hashing per message means the second
    # upload contributes only what is new.
    op.add_column("interaction", sa.Column("dedupe_hash", sa.String(64), nullable=True))
    op.create_index(
        "ix_interaction_tenant_dedupe",
        "interaction",
        ["tenant_id", "dedupe_hash"],
        unique=True,
        postgresql_where=sa.text("dedupe_hash IS NOT NULL"),
    )

    # Where a tenant's data came from and when. The owner needs to see coverage
    # rather than guess at it, and a continuous source (Gmail, and WhatsApp
    # later) needs somewhere to record its cursor between runs.
    op.create_table(
        "ingest_source",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False, index=True),
        # upload | gmail | whatsapp_cloud — the kind of source, not the file.
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("label", sa.String(300)),
        sa.Column("job_id", pg.UUID(as_uuid=True), index=True),
        sa.Column("messages", sa.Integer, default=0),
        sa.Column("duplicates", sa.Integer, default=0),
        sa.Column("skipped", sa.Integer, default=0),
        sa.Column("media", sa.Integer, default=0),
        sa.Column("bytes", sa.Integer, default=0),
        # Continuous sources resume from here; uploads leave it null.
        sa.Column("cursor", sa.String(200)),
        sa.Column("status", sa.String(24), default="done"),
        sa.Column("detail", sa.Text),
        # TenantScoped brings these two with it; a table that omits them
        # inserts fine in the model and fails at the database.
        sa.Column("attributes", pg.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime, nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_index("ix_ingest_source_tenant_created", "ingest_source",
                    ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ingest_source_tenant_created", table_name="ingest_source")
    op.drop_table("ingest_source")
    op.drop_index("ix_interaction_tenant_dedupe", table_name="interaction")
    op.drop_column("interaction", "dedupe_hash")
