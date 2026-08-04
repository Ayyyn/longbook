"""Invoices, payments, and the ledger.

The ledger is derived, not entered. Every entry points back to a source
document so the owner can always answer "why does it say I'm owed this?"
"""

from sqlalchemy import Column, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, SourceTracked, TenantScoped


class Invoice(Base, TenantScoped, SourceTracked):
    __tablename__ = "invoice"

    party_id = Column(UUID(as_uuid=True), ForeignKey("party.id"), index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("order.id"), nullable=True)
    invoice_no = Column(String(64), index=True)
    invoice_date = Column(Date)
    due_date = Column(Date, index=True)
    amount = Column(Numeric(14, 2))
    tax_amount = Column(Numeric(14, 2), default=0)
    status = Column(String(24), default="open")  # open | part_paid | paid | written_off


class Payment(Base, TenantScoped, SourceTracked):
    __tablename__ = "payment"

    party_id = Column(UUID(as_uuid=True), ForeignKey("party.id"), index=True)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoice.id"), nullable=True)
    amount = Column(Numeric(14, 2))
    mode = Column(String(24))                 # cash | upi | neft | cheque
    reference = Column(String(120))           # utr / cheque no
    received_on = Column(Date)
    cheque_date = Column(Date, nullable=True) # post-dated cheques are the norm


class LedgerEntry(Base, TenantScoped):
    __tablename__ = "ledger_entry"

    party_id = Column(UUID(as_uuid=True), ForeignKey("party.id"), index=True)
    entry_date = Column(Date, index=True)
    debit = Column(Numeric(14, 2), default=0)
    credit = Column(Numeric(14, 2), default=0)
    balance = Column(Numeric(14, 2))
    doc_type = Column(String(24))   # invoice | payment | adjustment
    doc_id = Column(UUID(as_uuid=True))
