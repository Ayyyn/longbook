"""Connected mailboxes.

Forwarding depends on the owner remembering to forward. A connected mailbox
does not, so the mail that carries invoices and purchase orders becomes
records on its own.

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_account",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("email", sa.String(200)),
        sa.Column("grant_id", sa.String(80)),
        sa.Column("status", sa.String(16), server_default="active"),
        sa.Column("synced_through", sa.DateTime()),
        sa.Column("last_checked_at", sa.DateTime()),
        sa.Column("last_error", sa.String(300)),
        sa.Column("attributes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_mail_account_tenant", "mail_account", ["tenant_id"])
    # The sweep looks up by grant when Nylas hands one back, and the callback
    # has to find an existing row for the same mailbox rather than add a
    # second one every time the owner reconnects.
    op.create_index("ix_mail_account_grant", "mail_account", ["grant_id"])


def downgrade() -> None:
    op.drop_table("mail_account")
