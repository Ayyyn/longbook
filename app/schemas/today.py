"""Response shapes for the Today screen."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class MoneyIn(BaseModel):
    today: float
    last_7_days: float
    payments_today: int


class OrdersToday(BaseModel):
    new_today: int
    new_last_7_days: int
    open_total: int
    awaiting_confirmation: int  # drafts the owner has not accepted yet


class RecentPayment(BaseModel):
    id: uuid.UUID
    party_name: str | None
    # None when the owner has not confirmed the amount yet. Deliberately not
    # 0.0 — a zero on this screen reads as "they paid nothing", which is a
    # different and much worse statement than "we do not know yet".
    amount: float | None
    mode: str | None
    received_on: date | None
    pending: bool = False


class Overdue(BaseModel):
    total: float
    parties: int
    worst_party: str | None = None
    worst_days: int = 0
    overdue_days: int = 45  # the tenant's own threshold, so the UI can say it


class ExceptionCounts(BaseModel):
    rate_deviations: int = 0
    stalled_orders: int = 0
    slowing_payers: int = 0
    total: int = 0
    headline: str | None = None  # the single most worth-reading one


class ChasingRow(BaseModel):
    """A party worth chasing today, worst first."""

    party_id: uuid.UUID
    party_name: str
    outstanding: float
    days_overdue: int


class FlaggedRow(BaseModel):
    """One exception, phrased as the owner would say it."""

    headline: str
    party_name: str | None = None
    kind: str  # rate_deviation | stalled_order | slowing_payer
    order_id: str | None = None
    party_id: uuid.UUID | None = None


class NewOrderRow(BaseModel):
    id: uuid.UUID
    party_name: str | None
    summary: str  # "Cotton 60x60 · 450 Meters"
    pending_fields: list[str] = Field(default_factory=list)


class TodayDigest(BaseModel):
    date: date
    money_in: MoneyIn
    orders: OrdersToday
    overdue: Overdue
    exceptions: ExceptionCounts
    dispatches_today: int
    needs_review: int
    agent_decisions_today: int
    recent_payments: list[RecentPayment] = Field(default_factory=list)

    # The screen is a list of things to do, not a grid of numbers.
    chasing: list[ChasingRow] = Field(default_factory=list)
    flagged: list[FlaggedRow] = Field(default_factory=list)
    new_orders: list[NewOrderRow] = Field(default_factory=list)

    # Facts the screen should label as not yet computed rather than show as 0.
    unavailable: list[str] = Field(default_factory=list)
