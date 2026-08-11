"""Finding the records a question can be answered from.

Two different jobs, done two different ways.

**The ledger is queried, not embedded.** "Who owes me the most" is an ORDER BY
over a computed balance, and no amount of vector similarity will get it right.
Embedding numbers is how you produce an answer that sounds correct and is off
by a lakh.

**Messages are searched with Postgres full-text.** Not pgvector — despite the
brief, the extension is not installed and nothing in this database has ever
been embedded. It would need the extension, a column, an embedding call per
message and a backfill over every tenant's history. It is also the wrong tool
here: these questions are entity-anchored ("what did we quote Ashok", "which
orders are undispatched"), which is what FTS is good at, over corpora of a few
thousand messages where recall is not the bottleneck. If retrieval turns out
weak on vaguer questions, pgvector is the upgrade — and it slots in here,
behind the same interface.

Every query in this module filters on tenant_id. That is the isolation
boundary; the prompt is not trusted to hold one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.models.catalog import Quality
from app.models.ingestion import Extraction, Interaction
from app.models.orders import Dispatch, Order, OrderLine
from app.models.party import Party
from app.services.ledger import outstanding_by_party
from app.services.sql import not_in_subquery, not_in_values

MAX_ROWS = 12
MAX_MESSAGES = 8


@dataclass
class Evidence:
    """One citable thing. A claim without one of these must not be made."""

    kind: str                    # party | order | payment | quote | message | dispatch
    label: str
    detail: str
    record_id: str | None = None
    party_id: str | None = None
    order_id: str | None = None
    interaction_id: str | None = None
    occurred_at: str | None = None


@dataclass
class Context:
    parties: list[Evidence] = field(default_factory=list)
    orders: list[Evidence] = field(default_factory=list)
    quotes: list[Evidence] = field(default_factory=list)
    messages: list[Evidence] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)
    # What the orders list was filtered to. Without saying so, a list of
    # undispatched orders is indistinguishable from a list of orders, and
    # the model refuses a question it was handed the answer to.
    orders_label: str = "Orders"

    @property
    def all(self) -> list[Evidence]:
        return [*self.parties, *self.orders, *self.quotes, *self.messages]

    @property
    def empty(self) -> bool:
        return not self.all and not self.totals


def _money(value) -> str:
    return f"Rs {float(value or 0):,.0f}"


# Ordinary question words. Without this a party called "Most Textiles" is
# "matched" by any question containing "most", and its records are dragged in
# as evidence for a question that has nothing to do with it.
STOPWORDS = {
    "what", "when", "which", "where", "whom", "whose", "does", "did", "have",
    "has", "there", "them", "they", "this", "that", "these", "those", "from",
    "with", "much", "many", "most", "least", "owes", "owed", "owe", "paid",
    "pay", "payment", "order", "orders", "rate", "rates", "quote", "quoted",
    "dispatch", "dispatched", "outstanding", "overdue", "days", "last", "year",
    "month", "week", "today", "still", "about", "been", "were", "was", "are",
    "and", "the", "for", "not", "any", "all", "show", "tell", "give", "list",
    "business", "customer", "customers", "party", "parties", "money", "total",
}


def _named_parties(db, tenant_id: uuid.UUID, question: str) -> list[Party]:
    """Parties the question appears to be about, by name fragment."""
    words = [
        w.strip(",.?!'\"")
        for w in question.split()
        if len(w.strip(",.?!'\"")) >= 4 and w.strip(",.?!'\"").lower() not in STOPWORDS
    ]
    if not words:
        return []
    clauses = [Party.name.ilike(f"%{w}%") for w in words[:8]]
    return db.execute(
        select(Party).where(Party.tenant_id == tenant_id, or_(*clauses)).limit(6)
    ).scalars().all()


def _outstanding(db, tenant_id: uuid.UUID, limit: int = MAX_ROWS) -> list[Evidence]:
    """Who owes what, straight from the ledger rather than from prose."""
    out: list[Evidence] = []
    as_of = datetime.utcnow().date()
    for row in outstanding_by_party(db, tenant_id, as_of)[:limit]:
        if not row.get("outstanding"):
            continue
        overdue = row.get("days_overdue") or 0
        out.append(
            Evidence(
                kind="party",
                label=row["party_name"],
                detail=(
                    f"{_money(row['outstanding'])} outstanding"
                    + (f", oldest bill {overdue} days past due" if overdue else "")
                ),
                party_id=str(row["party_id"]),
            )
        )
    return out


def _orders_for(
    db, tenant_id: uuid.UUID, party_ids: list[uuid.UUID] | None, undispatched: bool
) -> list[Evidence]:
    where = [Order.tenant_id == tenant_id]
    if party_ids:
        where.append(Order.party_id.in_(party_ids))
    if undispatched:
        # Both halves of the NOT IN trap, handled by construction rather than
        # by remembering: a NULL in the subquery would blank the predicate for
        # every row, and a NULL status would be dropped by a plain NOT IN.
        dispatched = select(Dispatch.order_id).where(Dispatch.tenant_id == tenant_id)
        where.append(not_in_subquery(Order.id, dispatched))
        where.append(not_in_values(Order.status, ["closed", "cancelled"]))

    rows = db.execute(
        select(Order, Party.name)
        .outerjoin(Party, Party.id == Order.party_id)
        .where(*where)
        .order_by(Order.order_date.desc().nullslast())
        .limit(MAX_ROWS)
    ).all()

    out: list[Evidence] = []
    for order, party_name in rows:
        lines = db.execute(
            select(OrderLine, Quality.code)
            .outerjoin(Quality, Quality.id == OrderLine.quality_id)
            .where(OrderLine.order_id == order.id)
        ).all()
        value = sum(float(x.quantity or 0) * float(x.rate or 0) for x, _ in lines)
        # Quantity and rate are both nullable — a partially-committed order is
        # the normal case, not an exception, and formatting must survive it.
        def describe(line, code) -> str:
            name = code or line.raw_description or "item"
            if line.quantity is None:
                return f"{name} (quantity not stated)"
            unit = f" {line.unit}" if line.unit else ""
            return f"{name} {float(line.quantity):g}{unit}"

        what = ", ".join(describe(x, code) for x, code in lines[:3])
        out.append(
            Evidence(
                kind="order",
                label=f"{party_name or 'Unknown party'} — {order.order_no or 'order'}",
                detail=(
                    f"{what or 'no items recorded'}"
                    + (f", {_money(value)}" if value else "")
                    + f", status {order.status or 'draft'}"
                ),
                record_id=str(order.id),
                order_id=str(order.id),
                party_id=str(order.party_id) if order.party_id else None,
                occurred_at=order.order_date.isoformat() if order.order_date else None,
            )
        )
    return out


def _quotes_for(db, tenant_id: uuid.UUID, party_ids: list[uuid.UUID]) -> list[Evidence]:
    """Rate history, which lives on extractions rather than a table."""
    if not party_ids:
        return []
    rows = db.execute(
        select(Extraction)
        .where(
            Extraction.tenant_id == tenant_id,
            Extraction.record_type == "quote",
            Extraction.status != "superseded",
        )
        .order_by(Extraction.created_at.desc())
        .limit(40)
    ).scalars().all()

    wanted = {str(p) for p in party_ids}
    out: list[Evidence] = []
    for row in rows:
        resolved = row.resolved or {}
        if str(resolved.get("party_id")) not in wanted:
            continue
        payload = row.payload or {}
        rate = payload.get("rate")
        if rate is None:
            continue
        out.append(
            Evidence(
                kind="quote",
                label=f"{payload.get('quality') or 'quote'} at {_money(rate)}",
                detail=f"status {payload.get('status') or 'offered'}",
                record_id=str(row.id),
                party_id=str(resolved.get("party_id")),
                interaction_id=str(row.interaction_id) if row.interaction_id else None,
                occurred_at=row.created_at.isoformat() if row.created_at else None,
            )
        )
        if len(out) >= MAX_ROWS:
            break
    return out


def _messages(db, tenant_id: uuid.UUID, question: str) -> list[Evidence]:
    """Full-text over this tenant's own messages."""
    terms = [w.strip(",.?!'\"") for w in question.split() if len(w.strip(",.?!'\"")) >= 4]
    if not terms:
        return []

    query = " | ".join(terms[:8])
    vector = func.to_tsvector("simple", func.coalesce(Interaction.body, ""))
    match = func.plainto_tsquery("simple", " ".join(terms[:8]))

    rows = db.execute(
        select(Interaction)
        .where(
            Interaction.tenant_id == tenant_id,
            Interaction.body.isnot(None),
            or_(
                vector.op("@@")(func.to_tsquery("simple", query)),
                *[Interaction.body.ilike(f"%{t}%") for t in terms[:4]],
            ),
        )
        .order_by(func.ts_rank(vector, match).desc(), Interaction.occurred_at.desc())
        .limit(MAX_MESSAGES)
    ).scalars().all()

    return [
        Evidence(
            kind="message",
            label=(r.sender or "message"),
            detail=(r.body or "")[:400],
            interaction_id=str(r.id),
            occurred_at=r.occurred_at.isoformat() if r.occurred_at else None,
        )
        for r in rows
    ]


def gather(db, tenant_id: uuid.UUID, question: str) -> Context:
    """Everything this tenant holds that could bear on the question.

    Deliberately broad rather than clever: the model is told to answer only
    from what is here and to cite it, so over-fetching costs tokens while
    under-fetching costs a wrong answer or a refusal.
    """
    lowered = question.lower()
    context = Context()

    parties = _named_parties(db, tenant_id, question)
    party_ids = [p.id for p in parties]

    asks_money = any(
        w in lowered
        for w in ("owe", "outstanding", "due", "overdue", "balance", "collect",
                  "payment", "paid", "baki", "udhaar")
    )
    asks_orders = any(
        w in lowered
        for w in ("order", "dispatch", "deliver", "pending", "sent", "supply")
    )
    asks_rates = any(
        w in lowered for w in ("rate", "quote", "quoted", "price", "bhav", "offer")
    )

    had_outstanding = False
    if asks_money or not (asks_orders or asks_rates):
        context.parties = _outstanding(db, tenant_id)
        had_outstanding = bool(context.parties)

    if parties and not context.parties:
        context.parties = [
            Evidence(kind="party", label=p.name,
                     detail=f"{p.city or ''} {p.phone or ''}".strip() or "party on record",
                     party_id=str(p.id))
            for p in parties
        ]

    undispatched = "dispatch" in lowered or "not sent" in lowered or "pending" in lowered
    if asks_orders or party_ids:
        context.orders = _orders_for(db, tenant_id, party_ids or None, undispatched)
        context.orders_label = (
            "Orders with NO dispatch recorded against them"
            if undispatched
            else "Orders"
        )

    if asks_rates or party_ids:
        context.quotes = _quotes_for(db, tenant_id, party_ids)

    context.messages = _messages(db, tenant_id, question)

    # An empty outstanding list is a fact, not an absence of records. Without
    # saying so, "who owes me the most" gets "I have no ledger records", which
    # reads as broken rather than as "nobody owes you anything".
    # Keyed on the ledger query, not on whether any party ended up in the
    # context — a party matched by name is not evidence that anyone owes
    # anything.
    if asks_money and not had_outstanding:
        context.totals["outstanding_summary"] = (
            "NIL RESULT: no party has any outstanding balance. Nobody owes "
            "this business anything."
        )
    if asks_orders and undispatched and not context.orders:
        context.totals["dispatch_summary"] = (
            "NIL RESULT: every order on record has a dispatch against it."
        )
    if asks_rates and party_ids and not context.quotes:
        context.totals["quote_summary"] = (
            "NIL RESULT: no quotes are on record for the party asked about."
        )

    context.totals = {
        **context.totals,
        "parties_on_record": db.execute(
            select(func.count()).select_from(Party).where(Party.tenant_id == tenant_id)
        ).scalar_one(),
        "orders_on_record": db.execute(
            select(func.count()).select_from(Order).where(Order.tenant_id == tenant_id)
        ).scalar_one(),
        "messages_on_record": db.execute(
            select(func.count()).select_from(Interaction)
            .where(Interaction.tenant_id == tenant_id)
        ).scalar_one(),
    }
    return context


def as_prompt(context: Context) -> str:
    """Render the evidence with the ids the answer has to cite."""
    if context.empty:
        return "NO RECORDS FOUND."

    blocks: list[str] = []

    def section(title: str, rows: list[Evidence]) -> None:
        if not rows:
            return
        lines = [f"## {title}"]
        for index, e in enumerate(rows, 1):
            ref = f"{e.kind[0].upper()}{index}"
            when = f" [{e.occurred_at[:10]}]" if e.occurred_at else ""
            lines.append(f"[{ref}] {e.label}{when} — {e.detail}")
        blocks.append("\n".join(lines))

    section("Outstanding and parties", context.parties)
    section(context.orders_label, context.orders)
    section("Quotes and rates", context.quotes)
    section("Messages", context.messages)

    totals = context.totals
    # Nil results are facts and are stated as such. "Nobody owes you anything"
    # and "I have no balance records" mean opposite things, and only one of
    # them is ever true.
    summary = "\n".join(
        value
        for key, value in totals.items()
        if key.endswith("_summary") and value
    )
    blocks.append(
        "## On record for this business\n"
        # Stated explicitly so "nobody owes anything" can be answered as the
        # fact it is, rather than as an absence the model has to interpret.
        + (f"{summary}\n" if summary else "")
        + f"{totals.get('parties_on_record', 0)} parties, "
        f"{totals.get('orders_on_record', 0)} orders, "
        f"{totals.get('messages_on_record', 0)} messages."
    )
    return "\n\n".join(blocks)


def citation_map(context: Context) -> dict[str, Evidence]:
    """[P1], [O2]… back to the record they came from."""
    out: dict[str, Evidence] = {}
    for title, rows in (
        ("P", context.parties), ("O", context.orders),
        ("Q", context.quotes), ("M", context.messages),
    ):
        for index, e in enumerate(rows, 1):
            out[f"{title}{index}"] = e
    return out


def recent_window(days: int = 365) -> tuple[date, date]:
    today = datetime.utcnow().date()
    return today - timedelta(days=days), today
