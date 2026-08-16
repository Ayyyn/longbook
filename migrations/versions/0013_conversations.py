"""Saved conversations and their messages.

The chat kept its history in the browser and lost it when the tab closed. That
was a deliberate choice — "a table of chat history is a liability with no
benefit the owner can see" — and it was the wrong one: an owner who worked out
on Tuesday which customers were slow to pay should find that on Thursday, from
a different phone.

Both tables hang off tenant with ON DELETE CASCADE, so "delete my data" keeps
meaning what the privacy page says it means.

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120)),
        sa.Column("attributes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_conversation_tenant", "conversation", ["tenant_id"])
    # The list is always "my conversations, newest first".
    op.create_index("ix_conversation_tenant_updated", "conversation",
                    ["tenant_id", "updated_at"])

    op.create_table(
        "chat_message",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", UUID(as_uuid=True),
                  sa.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("answered", sa.Boolean()),
        # Citations are stored with the answer. An answer without its evidence
        # is a claim with the proof torn off.
        sa.Column("sources", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("cost_usd", sa.Float()),
        sa.Column("attributes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_chat_message_tenant", "chat_message", ["tenant_id"])
    op.create_index("ix_chat_message_conversation", "chat_message", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("chat_message")
    op.drop_table("conversation")
