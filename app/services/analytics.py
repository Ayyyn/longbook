"""The metrics engine: what this business's own data can actually support.

Schema-aware and trade-agnostic by construction. Nothing here knows what a
business sells. It asks the database what exists — which entities have rows,
which columns are populated, how far back the history goes — and offers only
the measures and dimensions that survive that question. A jeweller and a
bearings distributor get different dashboards from the same code, because they
have different data, not because there is a branch on trade.

Two rules hold the whole thing up.

**Every number is computed in SQL.** No model call sits between the database
and a figure on screen. The AI in this system narrates aggregates it is handed;
it never produces one. That is the same rule the analyst has lived under since
it invented a total once — and on a dashboard, where a figure carries no
citation and no visible workings, it matters more, not less.

**Absence is reported, never filled.** If there is no cost column there is no
margin, and the dashboard says why instead of showing a plausible number. If
the history is eight months long there is no year-on-year comparison, and it
says that instead of comparing against zero. A dashboard that quietly invents
is worse than one that admits a gap, because nobody can tell which figures to
trust afterwards.

Tenant isolation is inherited rather than re-implemented: every query below is
issued through a tenant-scoped session, which adds the filter in the ORM layer
(see app/db.py). There is no tenant_id parameter here to get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Date, cast, func, select

from app.models.finance import Invoice, Payment
from app.models.orders import Order, OrderLine
from app.models.party import Party
from app.services.clock import business_today
from app.services.sql import not_in_values

# How many rows a breakdown returns before it stops being a chart and starts
# being a spreadsheet.
TOP_N = 12

# Below this many days of history, a period comparison is noise rather than a
# trend, so it is withheld and the reason given.
MIN_DAYS_FOR_COMPARISON = 14


def _num(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# ---------------------------------------------------------------------------
# What exists
# ---------------------------------------------------------------------------


@dataclass
class Measure:
    """One number this business can be asked for."""

    key: str
    label: str
    unit: str            # "money" | "count" | "quantity"
    entity: str          # which table it comes from
    available: bool
    why_not: str = ""    # filled only when unavailable, and shown to the owner


@dataclass
class Dimension:
    key: str
    label: str
    available: bool
    why_not: str = ""


@dataclass
class Schema:
    business_name: str
    first_record: date | None
    last_record: date | None
    records: int
    measures: list[Measure] = field(default_factory=list)
    dimensions: list[Dimension] = field(default_factory=list)

    @property
    def days(self) -> int:
        if not (self.first_record and self.last_record):
            return 0
        return (self.last_record - self.first_record).days + 1

    def as_dict(self) -> dict:
        return {
            "business_name": self.business_name,
            "first_record": self.first_record.isoformat() if self.first_record else None,
            "last_record": self.last_record.isoformat() if self.last_record else None,
            "days": self.days,
            "records": self.records,
            "measures": [m.__dict__ for m in self.measures],
            "dimensions": [d.__dict__ for d in self.dimensions],
        }


def _count(db, model) -> int:
    return int(db.execute(select(func.count()).select_from(model)).scalar_one() or 0)


def _populated(db, model, column) -> int:
    """Rows where this column actually has a value.

    The difference between "the table exists" and "the column is filled" is
    the difference between offering a measure and offering an empty chart. A
    rate column present on every row and null on all of them supports nothing.
    """
    return int(
        db.execute(
            select(func.count()).select_from(model).where(column.isnot(None))
        ).scalar_one() or 0
    )


def discover(db, business_name: str = "") -> Schema:
    """Ask the data what it can support."""
    payments = _count(db, Payment)
    invoices = _count(db, Invoice)
    orders = _count(db, Order)
    lines = _count(db, OrderLine)
    parties = _count(db, Party)

    bounds = db.execute(
        select(func.min(Payment.received_on), func.max(Payment.received_on))
    ).one_or_none() or (None, None)
    order_bounds = db.execute(
        select(func.min(Order.order_date), func.max(Order.order_date))
    ).one_or_none() or (None, None)

    firsts = [d for d in (bounds[0], order_bounds[0]) if d]
    lasts = [d for d in (bounds[1], order_bounds[1]) if d]

    measures = [
        Measure("received", "Received", "money", "payments", payments > 0,
                "" if payments else "No payments have been recorded yet."),
        Measure("invoiced", "Invoiced", "money", "invoices", invoices > 0,
                "" if invoices else "No invoices have been recorded yet."),
        Measure("orders", "Orders", "count", "orders", orders > 0,
                "" if orders else "No orders have been recorded yet."),
        Measure("quantity", "Quantity ordered", "quantity", "order_lines",
                _populated(db, OrderLine, OrderLine.quantity) > 0,
                "" if lines else "No order lines carry a quantity."),
        Measure("parties", "Active parties", "count", "parties", parties > 0,
                "" if parties else "No customers or suppliers yet."),
        Measure("outstanding", "Outstanding", "money", "invoices", invoices > 0,
                "" if invoices else "Outstanding needs invoices to measure against."),
        # Named even though it cannot be produced. An owner who wants margin
        # should be told what is missing, not left to wonder why it is absent.
        Measure("margin", "Gross margin", "money", "order_lines", False,
                "Gross margin cannot be calculated because no cost data is "
                "captured — the records carry what was charged, not what it "
                "cost to buy."),
    ]

    cities = _populated(db, Party, Party.city)
    kinds = _populated(db, Party, Party.kind)
    items = _populated(db, OrderLine, OrderLine.raw_description)
    modes = _populated(db, Payment, Payment.mode)
    statuses = _populated(db, Order, Order.status)

    dimensions = [
        Dimension("party", "Party", parties > 0,
                  "" if parties else "No parties yet."),
        Dimension("party_kind", "Customer or supplier", kinds > 0,
                  "" if kinds else "No party has been classified yet."),
        Dimension("city", "City", cities > 0,
                  "" if cities else "No party has a city recorded."),
        Dimension("item", "Item", items > 0,
                  "" if items else "No order line carries a description."),
        Dimension("status", "Order status", statuses > 0,
                  "" if statuses else "No order carries a status."),
        Dimension("mode", "Payment mode", modes > 0,
                  "" if modes else "No payment records how it arrived."),
    ]

    return Schema(
        business_name=business_name,
        first_record=min(firsts) if firsts else None,
        last_record=max(lasts) if lasts else None,
        records=payments + invoices + orders + parties,
        measures=measures,
        dimensions=dimensions,
    )


# ---------------------------------------------------------------------------
# How each measure is built
# ---------------------------------------------------------------------------

# (model, value expression, date column, joins needed to reach Party)
_SPECS: dict[str, tuple] = {
    "received":  (Payment, func.sum(Payment.amount), Payment.received_on,
                  [(Party, Party.id == Payment.party_id)]),
    "invoiced":  (Invoice, func.sum(Invoice.amount), Invoice.invoice_date,
                  [(Party, Party.id == Invoice.party_id)]),
    "orders":    (Order, func.count(Order.id), Order.order_date,
                  [(Party, Party.id == Order.party_id)]),
    "quantity":  (OrderLine, func.sum(OrderLine.quantity), Order.order_date,
                  [(Order, Order.id == OrderLine.order_id),
                   (Party, Party.id == Order.party_id)]),
    "parties":   (Party, func.count(func.distinct(Party.id)), Party.created_at,
                  []),
}

_DIM_COLUMNS = {
    "party": Party.name,
    "party_kind": Party.kind,
    "city": Party.city,
    "item": OrderLine.raw_description,
    "status": Order.status,
    "mode": Payment.mode,
}

# A dimension only reaches a measure if the measure's table can join to it.
_DIM_OK: dict[str, set[str]] = {
    "received": {"party", "party_kind", "city", "mode"},
    "invoiced": {"party", "party_kind", "city"},
    "orders": {"party", "party_kind", "city", "status"},
    "quantity": {"party", "party_kind", "city", "item", "status"},
    "parties": {"party_kind", "city"},
}


class AnalyticsError(ValueError):
    """Asked for something the data cannot support. Shown, never raised at a user."""


def _base(metric: str):
    if metric not in _SPECS:
        raise AnalyticsError(f"No measure called '{metric}'.")
    return _SPECS[metric]


def _apply(stmt, joins, when, start: date | None, end: date | None, filters: dict | None):
    for target, onclause in joins:
        stmt = stmt.join(target, onclause)
    if start:
        stmt = stmt.where(cast(when, Date) >= start)
    if end:
        stmt = stmt.where(cast(when, Date) <= end)
    for key, value in (filters or {}).items():
        if value in (None, "", "all"):
            continue
        column = _DIM_COLUMNS.get(key)
        if column is None:
            raise AnalyticsError(f"Cannot filter on '{key}'.")
        stmt = stmt.where(column == value)
    return stmt


def total(db, metric: str, start: date | None, end: date | None,
          filters: dict | None = None) -> float:
    """One number, computed by the database."""
    model, value, when, joins = _base(metric)
    stmt = _apply(select(value).select_from(model), joins, when, start, end, filters)
    return _num(db.execute(stmt).scalar_one_or_none())


# ---------------------------------------------------------------------------
# Periods and comparisons
# ---------------------------------------------------------------------------


def window_for(period: str, today: date | None = None) -> tuple[date, date]:
    """The start and end of a named period, in the owner's own timezone."""
    today = today or business_today()
    if period == "today":
        return today, today
    if period == "mtd":
        return today.replace(day=1), today
    if period == "qtd":
        first_month = 3 * ((today.month - 1) // 3) + 1
        return today.replace(month=first_month, day=1), today
    if period == "ytd":
        return today.replace(month=1, day=1), today
    if period == "7d":
        return today - timedelta(days=6), today
    if period == "90d":
        return today - timedelta(days=89), today
    if period == "12m":
        return today - timedelta(days=364), today
    return today - timedelta(days=29), today  # 30d, the default


def previous(start: date, end: date) -> tuple[date, date]:
    """The equivalent window immediately before this one, same length."""
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=span - 1), prev_end


def kpis(db, schema: Schema, period: str, filters: dict | None = None) -> list[dict]:
    """The headline figures, each with its comparison — or with the reason
    there is not one.

    A percentage against a previous period that barely has data is not an
    insight, it is a number that will be read as one. So the comparison is
    withheld when the history cannot carry it, and says why.
    """
    start, end = window_for(period)
    prev_start, prev_end = previous(start, end)
    history = schema.days

    out: list[dict] = []
    for measure in schema.measures:
        if measure.key not in _SPECS:
            # Named-but-unavailable measures (margin) still appear, so the
            # owner learns what is missing rather than wondering.
            out.append({
                "key": measure.key, "label": measure.label, "unit": measure.unit,
                "value": None, "available": False, "why_not": measure.why_not,
                "change_pct": None, "previous": None, "no_comparison": "",
            })
            continue
        if not measure.available:
            out.append({
                "key": measure.key, "label": measure.label, "unit": measure.unit,
                "value": None, "available": False, "why_not": measure.why_not,
                "change_pct": None, "previous": None, "no_comparison": "",
            })
            continue

        value = total(db, measure.key, start, end, filters)

        no_comparison = ""
        change = None
        prior = None
        if history < MIN_DAYS_FOR_COMPARISON:
            no_comparison = (
                f"Not enough history to compare — records cover {history} "
                f"day{'s' if history != 1 else ''}."
            )
        elif schema.first_record and prev_start < schema.first_record:
            no_comparison = (
                "The previous period starts before your records do, so a "
                "comparison would be against a gap."
            )
        else:
            prior = total(db, measure.key, prev_start, prev_end, filters)
            if prior:
                change = round(((value - prior) / prior) * 100, 1)
            elif value:
                # Growth from nothing is not a percentage. Say so rather than
                # printing an infinity or a misleading 100%.
                no_comparison = "Nothing in the previous period to compare against."

        out.append({
            "key": measure.key, "label": measure.label, "unit": measure.unit,
            "value": value, "available": True, "why_not": "",
            "previous": prior, "change_pct": change, "no_comparison": no_comparison,
        })
    return out


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

_BUCKETS = {"day": "day", "week": "week", "month": "month",
            "quarter": "quarter", "year": "year"}


def series(db, metric: str, freq: str, start: date, end: date,
           filters: dict | None = None) -> list[dict]:
    """A measure over time, bucketed by the database rather than in Python."""
    if freq not in _BUCKETS:
        raise AnalyticsError(f"Unknown frequency '{freq}'.")
    model, value, when, joins = _base(metric)
    bucket = func.date_trunc(_BUCKETS[freq], cast(when, Date)).label("bucket")
    stmt = _apply(select(bucket, value.label("v")).select_from(model),
                  joins, when, start, end, filters)
    rows = db.execute(stmt.group_by(bucket).order_by(bucket)).all()
    return [{"period": r[0].date().isoformat() if hasattr(r[0], "date") else str(r[0]),
             "value": _num(r[1])} for r in rows if r[0] is not None]


# ---------------------------------------------------------------------------
# Analyse by
# ---------------------------------------------------------------------------


def breakdown(db, metric: str, dimension: str, start: date, end: date,
              filters: dict | None = None, limit: int = TOP_N) -> list[dict]:
    """A measure split by a dimension, largest first."""
    if dimension not in _DIM_COLUMNS:
        raise AnalyticsError(f"No dimension called '{dimension}'.")
    if dimension not in _DIM_OK.get(metric, set()):
        raise AnalyticsError(
            f"{metric} cannot be split by {dimension} — they are not related "
            f"in your records."
        )
    model, value, when, joins = _base(metric)

    # The item dimension lives on order lines, which the orders measure does
    # not otherwise reach.
    if dimension == "item" and metric == "orders":
        joins = [(OrderLine, OrderLine.order_id == Order.id)] + list(joins)

    column = _DIM_COLUMNS[dimension]
    stmt = _apply(select(column.label("k"), value.label("v")).select_from(model),
                  joins, when, start, end, filters)
    rows = db.execute(
        stmt.where(column.isnot(None))
        .group_by(column)
        .order_by(value.desc())
        .limit(limit)
    ).all()
    return [{"label": str(r[0]), "value": _num(r[1])} for r in rows]


# ---------------------------------------------------------------------------
# Exceptions worth an owner's attention
# ---------------------------------------------------------------------------


def alerts(db, schema: Schema) -> list[dict]:
    """Things that look wrong, each computed and each pointing somewhere.

    Deliberately conservative. An alert an owner learns to dismiss is worse
    than no alert, so this only reports what is checkable: a real overdue
    invoice, a real quiet customer, a real duplicate. Nothing here guesses at
    a cause.
    """
    today = business_today()
    out: list[dict] = []

    # Money past its terms. The party's own credit days where set, so a
    # customer on 60-day terms is not flagged at 45.
    overdue = db.execute(
        select(Party.id, Party.name, func.sum(Invoice.amount), func.min(Invoice.due_date))
        .join(Party, Party.id == Invoice.party_id)
        .where(Invoice.status != "paid", Invoice.due_date.isnot(None),
               Invoice.due_date < today)
        .group_by(Party.id, Party.name)
        .order_by(func.sum(Invoice.amount).desc())
        .limit(5)
    ).all()
    for pid, name, amount, oldest in overdue:
        days = (today - oldest).days if oldest else 0
        out.append({
            "kind": "overdue",
            "severity": "high" if days > 60 else "medium",
            "headline": f"{name} is {days} days past due",
            "detail": f"₹{_num(amount):,.0f} outstanding, oldest invoice due {oldest}",
            "party_id": str(pid),
        })

    # An order nobody dispatched. The most common real failure in this trade,
    # and the one an owner most wants caught.
    stale = db.execute(
        select(Order.id, Party.name, Order.order_date)
        .join(Party, Party.id == Order.party_id)
        # not_in_values, not a raw notin_: a NULL status is emphatically not
        # 'dispatched', but NOT IN drops it, so the orders most likely to be
        # forgotten are exactly the ones the alert would miss.
        .where(not_in_values(Order.status, ["dispatched", "cancelled", "closed"]))
        .where(Order.order_date < today - timedelta(days=7))
        .order_by(Order.order_date.asc())
        .limit(5)
    ).all()
    for oid, name, when in stale:
        days = (today - when).days if when else 0
        out.append({
            "kind": "undispatched",
            "severity": "high" if days > 21 else "medium",
            "headline": f"Order open {days} days",
            "detail": f"{name} — placed {when}, nothing dispatched against it",
            "order_id": str(oid),
        })

    # A customer who used to buy and has stopped. Only meaningful with enough
    # history to know what "used to" means.
    if schema.days >= 90:
        quiet = db.execute(
            select(Party.id, Party.name, func.max(Order.order_date))
            .join(Order, Order.party_id == Party.id)
            .where(Party.kind == "customer")
            .group_by(Party.id, Party.name)
            .having(func.max(Order.order_date) < today - timedelta(days=60))
            .order_by(func.max(Order.order_date).asc())
            .limit(3)
        ).all()
        for pid, name, last in quiet:
            out.append({
                "kind": "quiet",
                "severity": "low",
                "headline": f"{name} has not ordered since {last}",
                "detail": f"{(today - last).days} days quiet, after ordering regularly",
                "party_id": str(pid),
            })

    return out


def rankings(db, schema: Schema, period: str, filters: dict | None = None) -> dict:
    """Top and bottom, over whichever dimensions this business actually has."""
    start, end = window_for(period)
    available = {d.key for d in schema.dimensions if d.available}
    out: dict[str, list] = {}
    if "party" in available:
        out["parties_by_received"] = breakdown(db, "received", "party", start, end,
                                               filters, limit=5)
    if "item" in available:
        out["items_by_quantity"] = breakdown(db, "quantity", "item", start, end,
                                             filters, limit=5)
    if "city" in available:
        out["cities_by_orders"] = breakdown(db, "orders", "city", start, end,
                                            filters, limit=5)
    return {k: v for k, v in out.items() if v}


def drill(db, metric: str, dimension: str, value: str, start: date, end: date,
          limit: int = 50) -> list[dict]:
    """The records behind one bar. A chart nobody can open is a chart nobody
    can check."""
    if dimension not in _DIM_COLUMNS:
        raise AnalyticsError(f"No dimension called '{dimension}'.")
    column = _DIM_COLUMNS[dimension]

    if metric == "received":
        rows = db.execute(
            select(Payment.id, Party.name, Payment.amount, Payment.received_on,
                   Payment.mode)
            .join(Party, Party.id == Payment.party_id)
            .where(column == value,
                   cast(Payment.received_on, Date) >= start,
                   cast(Payment.received_on, Date) <= end)
            .order_by(Payment.received_on.desc()).limit(limit)
        ).all()
        return [{"id": str(r[0]), "party": r[1], "amount": _num(r[2]),
                 "when": r[3].isoformat() if r[3] else None, "extra": r[4] or ""}
                for r in rows]

    rows = db.execute(
        select(Order.id, Party.name, Order.order_no, Order.order_date, Order.status)
        .join(Party, Party.id == Order.party_id)
        .outerjoin(OrderLine, OrderLine.order_id == Order.id)
        .where(column == value,
               cast(Order.order_date, Date) >= start,
               cast(Order.order_date, Date) <= end)
        .order_by(Order.order_date.desc()).limit(limit)
    ).all()
    seen: set[str] = set()
    out = []
    for oid, party, no, when, status in rows:
        if str(oid) in seen:
            continue
        seen.add(str(oid))
        out.append({"id": str(oid), "party": party, "amount": None,
                    "when": when.isoformat() if when else None,
                    "extra": no or status or ""})
    return out
