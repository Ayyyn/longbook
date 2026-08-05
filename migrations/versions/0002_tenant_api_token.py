"""Per-tenant bearer token digest.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("api_token_hash", sa.String(64), nullable=True))
    # Unique: two tenants sharing a token digest would be a silent cross-tenant
    # read. Indexed because it is looked up on every authenticated request.
    op.create_index("ix_tenant_api_token_hash", "tenant", ["api_token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_tenant_api_token_hash", table_name="tenant")
    op.drop_column("tenant", "api_token_hash")
