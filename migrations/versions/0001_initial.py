"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scoped() -> list[sa.Column]:
    """The TenantScoped mixin's columns, fresh for each table."""
    return [
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attributes", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]


def _sourced() -> list[sa.Column]:
    """The SourceTracked mixin's columns."""
    return [
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("source_ref", sa.String(256), nullable=True),
    ]


def _tenant_indexes(table: str) -> None:
    # Two indexes on the same column: TenantScoped declares both `index=True`
    # on tenant_id and an explicit Index in __table_args__. Reproduced as-is so
    # that `alembic revision --autogenerate` stays quiet; drop the redundant
    # one in a later migration if it shows up in disk-usage.
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.create_index(f"ix_{table}_tenant", table, ["tenant_id"])


def upgrade() -> None:
    # Trigram similarity is how the Resolver shortlists parties whose names
    # were typed four different ways.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "tenant",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_name", sa.String(200), nullable=False),
        sa.Column("owner_name", sa.String(120), nullable=True),
        sa.Column("owner_phone", sa.String(20), nullable=False, unique=True),
        sa.Column("city", sa.String(80), nullable=True),
        sa.Column("locale", sa.String(10), nullable=True),
        sa.Column("onboarded_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("plan", sa.String(32), nullable=True),
        sa.Column("paid_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "business_profile",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("version", sa.String(16), nullable=True),
        sa.Column("segments", pg.JSONB(), nullable=False),
        sa.Column("modules", pg.JSONB(), nullable=False),
        sa.Column("vocabulary", pg.JSONB(), nullable=False),
        sa.Column("rules", pg.JSONB(), nullable=False),
        sa.Column("examples", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "party",
        *_scoped(),
        *_sourced(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("aliases", pg.ARRAY(sa.String()), nullable=True),
        sa.Column("kind", sa.String(20), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("city", sa.String(80), nullable=True),
        sa.Column("gstin", sa.String(20), nullable=True),
        sa.Column("credit_days", sa.Integer(), nullable=True),
        sa.Column("credit_limit", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_walk_in", sa.Boolean(), nullable=True),
    )
    _tenant_indexes("party")
    op.create_index("ix_party_phone", "party", ["phone"])
    # Powers shortlist_parties() once a tenant's party list outgrows a seq scan.
    op.create_index(
        "ix_party_name_trgm", "party", ["name"], postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    op.create_table(
        "quality",
        *_scoped(),
        *_sourced(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("composition", sa.String(120), nullable=True),
        sa.Column("width_inch", sa.Numeric(6, 2), nullable=True),
        sa.Column("default_unit", sa.String(16), nullable=True),
        sa.Column("default_rate", sa.Numeric(12, 2), nullable=True),
    )
    _tenant_indexes("quality")
    op.create_index("ix_quality_code", "quality", ["code"])

    op.create_table(
        "lot",
        *_scoped(),
        *_sourced(),
        sa.Column("quality_id", pg.UUID(as_uuid=True), sa.ForeignKey("quality.id"), nullable=True),
        sa.Column("lot_no", sa.String(64), nullable=False),
        sa.Column("shade", sa.String(64), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit", sa.String(16), nullable=True),
    )
    _tenant_indexes("lot")
    op.create_index("ix_lot_quality_id", "lot", ["quality_id"])

    op.create_table(
        "order",
        *_scoped(),
        *_sourced(),
        sa.Column("party_id", pg.UUID(as_uuid=True), sa.ForeignKey("party.id"), nullable=True),
        sa.Column("order_no", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    _tenant_indexes("order")
    op.create_index("ix_order_party_id", "order", ["party_id"])
    op.create_index("ix_order_status", "order", ["status"])

    op.create_table(
        "order_line",
        *_scoped(),
        sa.Column(
            "order_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("order.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("quality_id", pg.UUID(as_uuid=True), sa.ForeignKey("quality.id"), nullable=True),
        sa.Column("lot_id", pg.UUID(as_uuid=True), sa.ForeignKey("lot.id"), nullable=True),
        sa.Column("raw_description", sa.String(300), nullable=True),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("unit", sa.String(16), nullable=True),
        sa.Column("rate", sa.Numeric(12, 2), nullable=True),
    )
    _tenant_indexes("order_line")

    op.create_table(
        "dispatch",
        *_scoped(),
        *_sourced(),
        sa.Column("order_id", pg.UUID(as_uuid=True), sa.ForeignKey("order.id"), nullable=True),
        sa.Column("challan_no", sa.String(64), nullable=True),
        sa.Column("transporter", sa.String(160), nullable=True),
        sa.Column("lr_no", sa.String(64), nullable=True),
        sa.Column("dispatched_on", sa.Date(), nullable=True),
        sa.Column("delivered_on", sa.Date(), nullable=True),
    )
    _tenant_indexes("dispatch")
    op.create_index("ix_dispatch_order_id", "dispatch", ["order_id"])

    op.create_table(
        "invoice",
        *_scoped(),
        *_sourced(),
        sa.Column("party_id", pg.UUID(as_uuid=True), sa.ForeignKey("party.id"), nullable=True),
        sa.Column("order_id", pg.UUID(as_uuid=True), sa.ForeignKey("order.id"), nullable=True),
        sa.Column("invoice_no", sa.String(64), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("tax_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(24), nullable=True),
    )
    _tenant_indexes("invoice")
    op.create_index("ix_invoice_party_id", "invoice", ["party_id"])
    op.create_index("ix_invoice_invoice_no", "invoice", ["invoice_no"])
    op.create_index("ix_invoice_due_date", "invoice", ["due_date"])

    op.create_table(
        "payment",
        *_scoped(),
        *_sourced(),
        sa.Column("party_id", pg.UUID(as_uuid=True), sa.ForeignKey("party.id"), nullable=True),
        sa.Column("invoice_id", pg.UUID(as_uuid=True), sa.ForeignKey("invoice.id"), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("mode", sa.String(24), nullable=True),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=True),
        sa.Column("cheque_date", sa.Date(), nullable=True),
    )
    _tenant_indexes("payment")
    op.create_index("ix_payment_party_id", "payment", ["party_id"])

    op.create_table(
        "ledger_entry",
        *_scoped(),
        sa.Column("party_id", pg.UUID(as_uuid=True), sa.ForeignKey("party.id"), nullable=True),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("debit", sa.Numeric(14, 2), nullable=True),
        sa.Column("credit", sa.Numeric(14, 2), nullable=True),
        sa.Column("balance", sa.Numeric(14, 2), nullable=True),
        sa.Column("doc_type", sa.String(24), nullable=True),
        sa.Column("doc_id", pg.UUID(as_uuid=True), nullable=True),
    )
    _tenant_indexes("ledger_entry")
    op.create_index("ix_ledger_entry_party_id", "ledger_entry", ["party_id"])
    op.create_index("ix_ledger_entry_entry_date", "ledger_entry", ["entry_date"])

    op.create_table(
        "interaction",
        *_scoped(),
        sa.Column("channel", sa.String(24), nullable=True),
        sa.Column("sender", sa.String(160), nullable=True),
        sa.Column("sender_phone", sa.String(20), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("media_uri", sa.String(400), nullable=True),
        sa.Column("media_kind", sa.String(24), nullable=True),
        sa.Column("detected_lang", sa.String(16), nullable=True),
        sa.Column("thread_key", sa.String(200), nullable=True),
    )
    _tenant_indexes("interaction")
    op.create_index("ix_interaction_sender_phone", "interaction", ["sender_phone"])
    op.create_index("ix_interaction_occurred_at", "interaction", ["occurred_at"])
    op.create_index("ix_interaction_thread_key", "interaction", ["thread_key"])

    op.create_table(
        "extraction",
        *_scoped(),
        sa.Column(
            "interaction_id", pg.UUID(as_uuid=True), sa.ForeignKey("interaction.id"), nullable=True
        ),
        sa.Column("record_type", sa.String(32), nullable=True),
        sa.Column("payload", pg.JSONB(), nullable=True),
        sa.Column("resolved", pg.JSONB(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), nullable=True),
        sa.Column("committed_type", sa.String(32), nullable=True),
        sa.Column("committed_id", pg.UUID(as_uuid=True), nullable=True),
    )
    _tenant_indexes("extraction")
    op.create_index("ix_extraction_interaction_id", "extraction", ["interaction_id"])
    op.create_index("ix_extraction_record_type", "extraction", ["record_type"])
    op.create_index("ix_extraction_status", "extraction", ["status"])

    op.create_table(
        "agent_run",
        *_scoped(),
        sa.Column("trace_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("agent", sa.String(48), nullable=True),
        sa.Column("model", sa.String(48), nullable=True),
        sa.Column("prompt_version", sa.String(24), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("decision", pg.JSONB(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("human_override", sa.Boolean(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    _tenant_indexes("agent_run")
    op.create_index("ix_agent_run_trace_id", "agent_run", ["trace_id"])
    op.create_index("ix_agent_run_agent", "agent_run", ["agent"])
    op.create_index("ix_agent_run_input_hash", "agent_run", ["input_hash"])


def downgrade() -> None:
    for table in (
        "agent_run",
        "extraction",
        "interaction",
        "ledger_entry",
        "payment",
        "invoice",
        "dispatch",
        "order_line",
        "order",
        "lot",
        "quality",
        "party",
        "business_profile",
        "tenant",
    ):
        op.drop_table(table)
    # pg_trgm is left installed: it is database-wide and something else may
    # have come to depend on it.
