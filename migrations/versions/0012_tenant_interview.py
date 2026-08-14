"""Keep the interview: the questions asked and the answers given.

Until now the interview was consumed and thrown away. `build_profile` rendered
the answers to prose, the Configurator digested that into segments, modules,
vocabulary and rules, and the raw exchange was gone. Three things were then
impossible: showing an owner what they had told us, letting them correct it,
and showing any of it to someone who abandoned onboarding halfway.

It lives on `tenant` rather than on `business_profile` deliberately. A profile
only exists once configure() has run, and the case that matters most is the
business that uploaded a file, answered two questions and stopped — which has
no profile at all. Storing it here means the record survives an incomplete
onboarding, which is exactly when it is most useful to look at.

Shape:
    {
      "questions": [{"id": ..., "question": ..., "hint": ..., "stage": ...}],
      "answers":   {"<question text>": "<answer>"},
      "asked_at":  iso8601,
      "answered_at": iso8601
    }

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column("interview", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("tenant", "interview")
