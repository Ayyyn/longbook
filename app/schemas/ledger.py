"""Response shapes for ledger and exception screens."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class OutstandingRow(BaseModel):
    party_id: uuid.UUID
    party_name: str
    outstanding: float
    days_overdue: int
    is_overdue: bool
    unapplied_credit: float
    oldest_bucket: str


class OutstandingSummary(BaseModel):
    as_of: date
    overdue_days: int
    total_outstanding: float
    total_overdue: float
    parties_overdue: int
    parties: list[OutstandingRow] = Field(default_factory=list)


class AgeingReport(BaseModel):
    as_of: date
    overdue_days: int
    buckets: dict[str, float]
    total: float


class LedgerEntryOut(BaseModel):
    date: date | None
    doc_type: str
    doc_id: str
    reference: str | None
    debit: float
    credit: float
    balance: float


class PartyLedger(BaseModel):
    party_id: uuid.UUID
    party_name: str
    as_of: date
    closing_balance: float
    days_overdue: int
    credit_days: int | None
    phone: str | None
    entries: list[LedgerEntryOut] = Field(default_factory=list)
    reminder_link: str | None = None


class RateDeviation(BaseModel):
    order_id: str
    order_no: str | None
    order_date: date | None
    party_name: str | None
    quality_code: str | None
    rate: float
    usual_rate: float
    deviation_pct: float
    direction: str


class StalledOrder(BaseModel):
    order_id: str
    order_no: str | None
    party_name: str | None
    status: str | None
    promised_date: date | None
    order_date: date | None
    late_by_days: int
    reason: str


class SlowingPayer(BaseModel):
    party_id: str
    party_name: str
    was_days: float
    now_days: float
    slower_by_days: float
    settlements: int
    outstanding: float


class Exceptions(BaseModel):
    as_of: date
    rate_deviations: list[RateDeviation] = Field(default_factory=list)
    stalled_orders: list[StalledOrder] = Field(default_factory=list)
    slowing_payers: list[SlowingPayer] = Field(default_factory=list)
    stale_drafts: int = 0
    total: int = 0
