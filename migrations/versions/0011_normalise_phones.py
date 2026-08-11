"""Store owner phone numbers as digits only, and fix the ones already stored.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-11

Numbers were stored in whatever shape the owner typed them: "98250 66554",
"+918104437601", "9619880684". Every lookup strips the query to digits and
matches on the last ten, so a stored number containing a space was invisible
to it — including to token recovery, which answers identically whether it
found a business or not. Two of three live tenants were unfindable, and the
owner would have had no way to know why no email arrived.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # regexp_replace with 'g' strips spaces, plus signs, dashes and brackets.
    # Existing rows are already unique on the raw string; normalising cannot
    # introduce a collision unless two rows differ only by punctuation, which
    # would have been the same business twice and is worth failing loudly on.
    op.execute(
        "UPDATE tenant SET owner_phone = regexp_replace(owner_phone, '[^0-9]', '', 'g') "
        "WHERE owner_phone IS NOT NULL "
        "AND owner_phone <> regexp_replace(owner_phone, '[^0-9]', '', 'g')"
    )


def downgrade() -> None:
    # Nothing to restore: the original punctuation carried no information.
    pass
