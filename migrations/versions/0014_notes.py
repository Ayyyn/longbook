"""Notes.

A great deal of what a business knows fits neither a party nor an order —
who is taking over the firm after Diwali, which transporter not to use on a
Friday, what to keep aside for a reorder. Until now that lived in the owner's
memory, which is the thing this product exists to replace.

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("media_uri", sa.String(500)),
        sa.Column("media_kind", sa.String(24)),
        sa.Column("media_mime", sa.String(80)),
        sa.Column("caption", sa.String(300)),
        sa.Column("source", sa.String(16), server_default="typed"),
        sa.Column("attributes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_note_tenant", "note", ["tenant_id"])
    # The list is always "mine, newest first".
    op.create_index("ix_note_tenant_created", "note", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_table("note")
