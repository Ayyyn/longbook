"""Per-tenant inbound forwarding address.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The tag in textiles.diri+<slug>@gmail.com. Unique and indexed because
    # every inbound mail is resolved to a tenant by this one lookup, and two
    # businesses sharing a slug would mean one reading the other's invoices.
    op.add_column("tenant", sa.Column("inbound_slug", sa.String(24), nullable=True))
    op.create_index("ix_tenant_inbound_slug", "tenant", ["inbound_slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tenant_inbound_slug", table_name="tenant")
    op.drop_column("tenant", "inbound_slug")
