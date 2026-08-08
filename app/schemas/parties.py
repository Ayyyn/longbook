"""Response shapes for the Parties screens."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.ledger import LedgerEntryOut


class PartyRow(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    city: str | None
    kind: str | None
    credit_days: int | None
    outstanding: float
    days_overdue: int
    is_overdue: bool
    last_order_on: str | None = None
    orders: int = 0
    # How the owner would describe them in one line.
    summary: str = ""


class PartySummary(BaseModel):
    parties: list[PartyRow] = Field(default_factory=list)
    total: int
    total_outstanding: float
    overdue_days: int


class PartyBrief(BaseModel):
    """Auto-generated memory of a customer. Every claim traceable."""

    version: int = 0
    buys: list[dict[str, Any]] = Field(default_factory=list)
    rate_band: dict[str, Any] = Field(default_factory=dict)
    payment_behaviour: dict[str, Any] = Field(default_factory=dict)
    complaints: dict[str, Any] = Field(default_factory=dict)
    # Negotiation history. Quotes commit nothing, so they live here to be
    # read rather than in the queue to be approved.
    quotes: dict[str, Any] = Field(default_factory=dict)
    contact: dict[str, Any] = Field(default_factory=dict)
    totals: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, Any] = Field(default_factory=dict)
    generated_at: str | None = None
    watermark: str | None = None


class OrderRow(BaseModel):
    id: str
    order_no: str | None
    status: str | None
    order_date: date | None
    promised_date: date | None
    lines: int = 0
    party_name: str | None = None
    pending_fields: list[str] = Field(default_factory=list)


class PartyDetail(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    city: str | None
    gstin: str | None
    kind: str | None
    credit_days: int | None
    aliases: list[str] = Field(default_factory=list)

    outstanding: float
    days_overdue: int
    closing_balance: float

    brief: PartyBrief
    entries: list[LedgerEntryOut] = Field(default_factory=list)
    orders: list[OrderRow] = Field(default_factory=list)
    reminder_link: str | None = None


class OrderLineOut(BaseModel):
    quality: str | None
    quantity: float | None
    unit: str | None
    rate: float | None


class OrderDetail(BaseModel):
    id: uuid.UUID
    order_no: str | None
    status: str | None
    order_date: date | None
    promised_date: date | None
    notes: str | None
    party_id: uuid.UUID | None
    party_name: str | None
    lines: list[OrderLineOut] = Field(default_factory=list)
    value: float = 0.0
    pending_fields: list[str] = Field(default_factory=list)
    dispatched: bool = False
    # What happened to it, newest first.
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    dispatch: dict[str, Any] | None = None

    # "Why does it say this?" — the conversation and the agent trail behind it.
    extraction_id: uuid.UUID | None = None
    trace_id: uuid.UUID | None = None
    conversation: list[dict[str, Any]] = Field(default_factory=list)


class OrderPage(BaseModel):
    orders: list[OrderRow] = Field(default_factory=list)
    total: int
    by_status: dict[str, int] = Field(default_factory=dict)
