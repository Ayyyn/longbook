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
    amount: float
    mode: str | None
    received_on: date | None


class TodayDigest(BaseModel):
    date: date
    money_in: MoneyIn
    orders: OrdersToday
    dispatches_today: int
    needs_review: int
    agent_decisions_today: int
    recent_payments: list[RecentPayment] = Field(default_factory=list)

    # Facts the screen should label as not yet computed rather than show as 0.
    unavailable: list[str] = Field(default_factory=list)
