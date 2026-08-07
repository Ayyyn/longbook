"""Deterministic ledger maths. No model calls in here — these numbers must be
reproducible and explainable to an owner who will check them against Tally.

Everything below is built on one idea: most payments in this business arrive
without saying which bill they settle ("aaj 50000 rtgs kar diya"). So an
unallocated payment is applied to that party's oldest unpaid invoice first —
FIFO, the same convention every Indian accountant uses when a customer sends a
round figure. It is not a guess about intent; it is the stated convention, and
it is what makes an ageing bucket defensible when the owner queries it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from app.models.finance import Invoice, Payment
from app.models.ledger_state import LedgerWatermark
from app.models.party import Party

# Deteriorating means "slower than they used to be by more than a fortnight",
# not "paid late once". Below this, it is noise the owner should not be shown.
TREND_WORSENING_DAYS = 14
MIN_SETTLEMENTS_PER_HALF = 2

NOT_DUE = "current"

# Money fields that, while unconfirmed, make a row unsafe to count. A payment
# whose amount nobody has confirmed must not reduce what a customer owes.
_UNCONFIRMED_MONEY = ("amount", "rate", "balance")


def _confirmed(model):
    """Rows whose money the owner has actually confirmed.

    Field-level gating writes a record as soon as *some* of it is certain, so
    a partially-known payment exists in the table. It is excluded here rather
    than at write time, because the owner still needs to see it in the queue —
    it just must not move a total until they answer.
    """
    pending = model.attributes["pending_fields"]
    # `?` (has_key) tests membership of a JSONB array directly. Containment
    # was the obvious reach but casting a Python string to JSONB serialises it
    # as a JSON *string*, so `["amount"] @> "[\"amount\"]"` was always false
    # and every unconfirmed row silently passed the filter.
    return sa.or_(
        pending.is_(None),
        sa.not_(sa.or_(*[pending.has_key(field) for field in _UNCONFIRMED_MONEY])),
    )


@dataclass
class OpenItem:
    invoice_id: uuid.UUID
    invoice_no: str | None
    due_date: date | None
    amount: Decimal
    remaining: Decimal

    def days_overdue(self, as_of: date) -> int:
        if self.due_date is None or self.due_date >= as_of:
            return 0
        return (as_of - self.due_date).days


@dataclass
class Settlement:
    """A payment matched to an invoice, and how late it was."""

    paid_on: date
    lag_days: int
    amount: Decimal


@dataclass
class PartyPosition:
    party_id: uuid.UUID
    name: str
    open_items: list[OpenItem] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    unapplied_credit: Decimal = Decimal(0)

    @property
    def outstanding(self) -> Decimal:
        return sum((item.remaining for item in self.open_items), Decimal(0))

    def days_overdue(self, as_of: date) -> int:
        """Age of the oldest thing *still unpaid* — how the owner thinks of it.

        Settled invoices are excluded deliberately: a customer who cleared a
        90-day-old bill last week is not 90 days overdue, and counting them as
        such would put them in the digest every evening forever.
        """
        return max(
            (item.days_overdue(as_of) for item in self.open_items if item.remaining > 0),
            default=0,
        )


def _d(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def party_positions(db, tenant_id, as_of: date) -> dict[uuid.UUID, PartyPosition]:
    """Allocate every payment against that party's invoices, oldest first.

    The single pass behind ageing, overdue crossings and payment trend, so all
    three always agree with each other.
    """
    positions: dict[uuid.UUID, PartyPosition] = {}

    parties = db.execute(
        select(Party.id, Party.name).where(Party.tenant_id == tenant_id)
    ).all()
    for party_id, name in parties:
        positions[party_id] = PartyPosition(party_id=party_id, name=name)

    invoices = db.execute(
        select(Invoice)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.party_id.isnot(None),
            Invoice.invoice_date <= as_of,
            Invoice.status != "written_off",
            _confirmed(Invoice),
        )
        .order_by(Invoice.due_date.asc().nullsfirst(), Invoice.invoice_date.asc())
    ).scalars().all()

    by_invoice: dict[uuid.UUID, OpenItem] = {}
    for invoice in invoices:
        position = positions.get(invoice.party_id)
        if position is None:
            continue
        total = _d(invoice.amount) + _d(invoice.tax_amount)
        item = OpenItem(
            invoice_id=invoice.id,
            invoice_no=invoice.invoice_no,
            due_date=invoice.due_date or invoice.invoice_date,
            amount=total,
            remaining=total,
        )
        position.open_items.append(item)
        by_invoice[invoice.id] = item

    payments = db.execute(
        select(Payment)
        .where(
            Payment.tenant_id == tenant_id,
            Payment.party_id.isnot(None),
            Payment.received_on <= as_of,
            _confirmed(Payment),
        )
        .order_by(Payment.received_on.asc().nullsfirst(), Payment.created_at.asc())
    ).scalars().all()

    for payment in payments:
        position = positions.get(payment.party_id)
        if position is None:
            continue
        left = _d(payment.amount)
        paid_on = payment.received_on or as_of

        # A payment that names its invoice settles that invoice whatever its
        # age; anything left over falls through to the oldest bills.
        named = by_invoice.get(payment.invoice_id) if payment.invoice_id else None
        targets = [named] if named is not None else []
        targets += [
            item
            for item in position.open_items
            if item.remaining > 0 and item is not named
        ]

        for item in targets:
            if left <= 0:
                break
            if item.remaining <= 0:
                continue
            applied = min(left, item.remaining)
            item.remaining -= applied
            left -= applied
            if item.remaining == 0 and item.due_date:
                position.settlements.append(
                    Settlement(
                        paid_on=paid_on,
                        lag_days=(paid_on - item.due_date).days,
                        amount=item.amount,
                    )
                )

        # Money in with no bill to put it against — an advance, or a bill this
        # system has not seen. Carried, never silently dropped.
        if left > 0:
            position.unapplied_credit += left

    return positions


def bucket_edges(overdue_days: int) -> list[int]:
    """Bucket boundaries in days past due.

    The tenant's own threshold is always a boundary, so the number the digest
    alerts on is the same number the ageing table shows.
    """
    return sorted({30, 60, 90} | {int(overdue_days)})


def bucket_labels(overdue_days: int) -> list[str]:
    edges = bucket_edges(overdue_days)
    labels = [NOT_DUE]
    low = 1
    for edge in edges:
        labels.append(f"{low}-{edge}")
        low = edge + 1
    labels.append(f"{edges[-1]}+")
    return labels


def _bucket_for(days: int, overdue_days: int) -> str:
    if days <= 0:
        return NOT_DUE
    low = 1
    for edge in bucket_edges(overdue_days):
        if days <= edge:
            return f"{low}-{edge}"
        low = edge + 1
    return f"{bucket_edges(overdue_days)[-1]}+"


def ageing_buckets(db, tenant_id, as_of: date, overdue_days: int = 45) -> dict[str, float]:
    """0-30 / 31-45 / 46-60 / 60+ outstanding, per the profile's overdue_days."""
    buckets = {label: Decimal(0) for label in bucket_labels(overdue_days)}

    for position in party_positions(db, tenant_id, as_of).values():
        for item in position.open_items:
            if item.remaining <= 0:
                continue
            buckets[_bucket_for(item.days_overdue(as_of), overdue_days)] += item.remaining

    return {label: float(amount) for label, amount in buckets.items()}


def outstanding_by_party(db, tenant_id, as_of: date, overdue_days: int = 45) -> list[dict]:
    """Who owes what, worst first. Read-only — safe for any screen to call."""
    rows = []
    for position in party_positions(db, tenant_id, as_of).values():
        outstanding = position.outstanding
        if outstanding <= 0:
            continue
        days = position.days_overdue(as_of)
        rows.append(
            {
                "party_id": position.party_id,
                "party_name": position.name,
                "outstanding": float(outstanding),
                "days_overdue": days,
                "is_overdue": days >= overdue_days,
                "unapplied_credit": float(position.unapplied_credit),
                "oldest_bucket": _bucket_for(days, overdue_days),
            }
        )
    rows.sort(key=lambda r: (-r["days_overdue"], -r["outstanding"]))
    return rows


def overdue_crossings(db, tenant_id, as_of: date, overdue_days: int) -> list[dict]:
    """Parties that crossed the threshold since the last run — the alert that
    makes the daily digest worth opening.

    Stateful by design: it reads the watermark from the previous run, reports
    only the difference, and rewrites it. Calling it twice in one day returns
    nothing the second time, which is the point — do not wire it to a screen.
    """
    watermarks = {
        w.party_id: w
        for w in db.execute(
            select(LedgerWatermark).where(LedgerWatermark.tenant_id == tenant_id)
        ).scalars().all()
    }

    crossings: list[dict] = []
    for position in party_positions(db, tenant_id, as_of).values():
        outstanding = position.outstanding
        days = position.days_overdue(as_of)
        is_overdue = bool(outstanding > 0 and days >= overdue_days)

        mark = watermarks.get(position.party_id)
        if mark is None:
            mark = LedgerWatermark(tenant_id=tenant_id, party_id=position.party_id)
            db.add(mark)
            # A party already overdue on the very first run has not "crossed"
            # anything — reporting it would make day one a wall of alerts about
            # history the owner already knows.
            was_overdue = is_overdue
        else:
            was_overdue = bool(mark.was_overdue)

        if is_overdue and not was_overdue:
            crossings.append(
                {
                    "party_id": str(position.party_id),
                    "party_name": position.name,
                    "outstanding": float(outstanding),
                    "days_overdue": days,
                    "crossed_on": str(as_of),
                }
            )

        mark.was_overdue = is_overdue
        mark.days_overdue = days
        mark.outstanding = outstanding
        mark.last_run_on = as_of

    db.flush()
    crossings.sort(key=lambda c: (-c["outstanding"], -c["days_overdue"]))
    return crossings


def payment_trend(db, tenant_id, lookback_days: int = 180) -> list[dict]:
    """Parties whose average days-to-pay is deteriorating.

    Compares the two halves of the window. A party needs settlements in both
    halves to be judged at all: one late payment after a quiet spell is not a
    trend, and calling it one costs the owner a relationship.
    """
    as_of = date.today()
    window_start = as_of - timedelta(days=lookback_days)
    midpoint = as_of - timedelta(days=lookback_days // 2)

    flags: list[dict] = []
    for position in party_positions(db, tenant_id, as_of).values():
        earlier = [s.lag_days for s in position.settlements if window_start <= s.paid_on < midpoint]
        recent = [s.lag_days for s in position.settlements if s.paid_on >= midpoint]

        if len(earlier) < MIN_SETTLEMENTS_PER_HALF or len(recent) < MIN_SETTLEMENTS_PER_HALF:
            continue

        was = sum(earlier) / len(earlier)
        now = sum(recent) / len(recent)
        if now - was < TREND_WORSENING_DAYS:
            continue

        flags.append(
            {
                "party_id": str(position.party_id),
                "party_name": position.name,
                "was_days": round(was, 1),
                "now_days": round(now, 1),
                "slower_by_days": round(now - was, 1),
                "settlements": len(earlier) + len(recent),
                "outstanding": float(position.outstanding),
            }
        )

    flags.sort(key=lambda f: -f["slower_by_days"])
    return flags


def party_ledger(db, tenant_id, party_id, as_of: date) -> dict:
    """Every document behind a party's balance, with a running total.

    Derived on read rather than stored: the owner's first question about any
    number here is "why", and a recomputed statement can never drift from the
    invoices and payments it is made of.
    """
    invoices = db.execute(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.party_id == party_id,
            Invoice.invoice_date <= as_of,
            _confirmed(Invoice),
        )
    ).scalars().all()
    payments = db.execute(
        select(Payment).where(
            Payment.tenant_id == tenant_id,
            Payment.party_id == party_id,
            Payment.received_on <= as_of,
            _confirmed(Payment),
        )
    ).scalars().all()

    entries = [
        {
            "date": invoice.invoice_date,
            "doc_type": "invoice",
            "doc_id": str(invoice.id),
            "reference": invoice.invoice_no,
            "debit": float(_d(invoice.amount) + _d(invoice.tax_amount)),
            "credit": 0.0,
        }
        for invoice in invoices
    ] + [
        {
            "date": payment.received_on,
            "doc_type": "payment",
            "doc_id": str(payment.id),
            "reference": payment.reference or payment.mode,
            "debit": 0.0,
            "credit": float(_d(payment.amount)),
        }
        for payment in payments
    ]

    entries.sort(key=lambda e: (e["date"] or as_of, e["doc_type"]))

    balance = 0.0
    for entry in entries:
        balance += entry["debit"] - entry["credit"]
        entry["balance"] = round(balance, 2)

    return {"entries": entries, "closing_balance": round(balance, 2)}
