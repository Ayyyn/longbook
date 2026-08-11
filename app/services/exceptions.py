"""Exception flagging: the things worth interrupting an owner about.

Deterministic, like the ledger — an exception the owner cannot reproduce is an
exception they stop trusting. The model's only job (in LedgerAnalyst) is to
write the sentence explaining a flag, never to decide there is one.

Each rule answers a question the owner would otherwise have to remember to ask:
  rate deviation   — did I quote this cheaper than I normally do?
  stalled orders   — what did I promise and not send?
  deteriorating    — who is paying slower than they used to? (see ledger.py)
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import func, select

from app.models.catalog import Item
from app.models.orders import Dispatch, Order, OrderLine
from app.models.party import Party
from app.services.clock import business_today
from app.services.sql import not_in_subquery

# A quality needs a bit of history before "normal" means anything.
MIN_RATES_FOR_BASELINE = 3
RECENT_LINES = 400

OPEN_STATUSES = ("draft", "confirmed", "partially_dispatched")
DEFAULT_STALL_DAYS = 7


def _d(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def rate_deviations(
    db, tenant_id: uuid.UUID, threshold_pct: float = 20.0, as_of: date | None = None
) -> list[dict]:
    """Order lines priced well away from what this quality usually fetches.

    Baseline is the median of that quality's other rates, not the mean: one
    bulk deal at half price should not quietly redefine normal and hide the
    next three.
    """
    as_of = as_of or business_today()

    rows = db.execute(
        select(OrderLine, Order, Item.code, Party.name)
        .join(Order, Order.id == OrderLine.order_id)
        .outerjoin(Item, Item.id == OrderLine.item_id)
        .outerjoin(Party, Party.id == Order.party_id)
        .where(
            OrderLine.tenant_id == tenant_id,
            OrderLine.rate.isnot(None),
            OrderLine.item_id.isnot(None),
        )
        .order_by(Order.order_date.desc().nullslast())
        .limit(RECENT_LINES)
    ).all()

    by_quality: dict[uuid.UUID, list[Decimal]] = {}
    for line, _order, _code, _party in rows:
        by_quality.setdefault(line.item_id, []).append(_d(line.rate))

    flags: list[dict] = []
    for line, order, code, party_name in rows:
        rates = by_quality.get(line.item_id, [])
        if len(rates) < MIN_RATES_FOR_BASELINE:
            continue

        others = list(rates)
        others.remove(_d(line.rate))  # compare against everything but itself
        if len(others) < MIN_RATES_FOR_BASELINE - 1:
            continue

        baseline = median(others)
        if baseline <= 0:
            continue

        deviation = (_d(line.rate) - baseline) / baseline * 100
        if abs(deviation) < threshold_pct:
            continue

        flags.append(
            {
                "order_id": str(order.id),
                "order_no": order.order_no,
                "order_date": order.order_date,
                "party_name": party_name,
                "quality_code": code,
                "rate": float(line.rate),
                "usual_rate": float(baseline),
                "deviation_pct": round(float(deviation), 1),
                "direction": "below" if deviation < 0 else "above",
            }
        )

    flags.sort(key=lambda f: -abs(f["deviation_pct"]))
    return flags


def stalled_orders(
    db, tenant_id: uuid.UUID, as_of: date | None = None, stall_days: int = DEFAULT_STALL_DAYS
) -> list[dict]:
    """Open orders past their promised date with nothing dispatched.

    An order with no promised date is judged on age instead, because "I said
    I'd send it" is a promise whether or not anyone wrote a date down.
    """
    as_of = as_of or business_today()

    dispatched = select(Dispatch.order_id).where(Dispatch.tenant_id == tenant_id)

    rows = db.execute(
        select(Order, Party.name)
        .outerjoin(Party, Party.id == Order.party_id)
        .where(
            Order.tenant_id == tenant_id,
            Order.status.in_(OPEN_STATUSES),
            not_in_subquery(Order.id, dispatched),
        )
    ).all()

    flags: list[dict] = []
    for order, party_name in rows:
        if order.promised_date:
            late_by = (as_of - order.promised_date).days
            reason = "past promised date"
        elif order.order_date:
            late_by = (as_of - order.order_date).days - stall_days
            reason = f"open {(as_of - order.order_date).days} days, no dispatch"
        else:
            continue

        if late_by <= 0:
            continue

        flags.append(
            {
                "order_id": str(order.id),
                "order_no": order.order_no,
                "party_name": party_name,
                "status": order.status,
                "promised_date": order.promised_date,
                "order_date": order.order_date,
                "late_by_days": late_by,
                "reason": reason,
            }
        )

    flags.sort(key=lambda f: -f["late_by_days"])
    return flags


def stale_drafts(db, tenant_id: uuid.UUID, as_of: date | None = None, older_than: int = 3) -> int:
    """Orders auto-committed from chat that nobody has confirmed.

    Not an exception in itself, but a large number means the owner has stopped
    reading the queue, which is worth knowing before the data drifts.
    """
    as_of = as_of or business_today()
    cutoff = as_of - timedelta(days=older_than)
    return db.execute(
        select(func.count())
        .select_from(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.status == "draft",
            Order.order_date.isnot(None),
            Order.order_date < cutoff,
        )
    ).scalar_one()
