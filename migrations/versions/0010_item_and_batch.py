"""Rename quality -> item and lot -> batch.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-11

The words were the fabric trade's, not the product's. A machinery dealer does
not have qualities and a chemical distributor does not have dye lots; both
have items, and some of them have batches. What each business *calls* them is
display, driven by BusinessProfile.vocabulary, and does not belong in a
table name.

Renames rather than create-and-copy so existing rows, their ids and their
foreign keys survive untouched. Postgres DDL is transactional, so this either
lands whole or not at all — there is no state where order_line points at a
table that no longer exists.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("quality", "item")
    op.rename_table("lot", "batch")

    # The FK constraints follow the table automatically; the columns naming
    # them do not.
    op.alter_column("batch", "quality_id", new_column_name="item_id")
    op.alter_column("order_line", "quality_id", new_column_name="item_id")
    op.alter_column("order_line", "lot_id", new_column_name="batch_id")

    # Indexes created under the old names still work but read as a lie in
    # \d output, which is where the next person looks.
    op.execute("ALTER INDEX IF EXISTS ix_quality_tenant RENAME TO ix_item_tenant")
    op.execute("ALTER INDEX IF EXISTS ix_lot_tenant RENAME TO ix_batch_tenant")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS ix_item_tenant RENAME TO ix_quality_tenant")
    op.execute("ALTER INDEX IF EXISTS ix_batch_tenant RENAME TO ix_lot_tenant")
    op.alter_column("order_line", "batch_id", new_column_name="lot_id")
    op.alter_column("order_line", "item_id", new_column_name="quality_id")
    op.alter_column("batch", "item_id", new_column_name="quality_id")
    op.rename_table("batch", "lot")
    op.rename_table("item", "quality")
