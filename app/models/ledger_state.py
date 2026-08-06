"""Watermark for diff-based overdue alerts.

`overdue_crossings` has to answer "who crossed the line *since the last run*",
not "who is over the line", or the digest repeats the same five parties every
evening until the owner stops reading it. That needs memory of the previous
run, which is what this table is.

One row per party per tenant, rewritten on each analyst run.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TenantScoped


class LedgerWatermark(Base, TenantScoped):
    __tablename__ = "ledger_watermark"

    party_id = Column(UUID(as_uuid=True), ForeignKey("party.id", ondelete="CASCADE"), index=True)

    was_overdue = Column(Boolean, default=False, nullable=False)
    days_overdue = Column(Integer, default=0)
    outstanding = Column(Numeric(14, 2), default=0)
    last_run_on = Column(Date)

    # Declaring __table_args__ here overrides the one TenantScoped supplies, so
    # the tenant index has to be repeated rather than inherited.
    __table_args__ = (
        Index("ix_ledger_watermark_tenant", "tenant_id"),
        UniqueConstraint("tenant_id", "party_id", name="uq_ledger_watermark_party"),
    )
