"""Owner email, for the close-of-business digest.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("owner_email", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant", "owner_email")
