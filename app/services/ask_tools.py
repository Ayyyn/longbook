"""The lookups the analyst can choose to make.

The old design pre-computed a context by keyword-matching the question:

    asks_money = any(w in lowered for w in ("owe", "outstanding", "due", ...))

which answers "who owes me money" and returns nothing at all for "kya chal
raha hai", "anything stuck with Mahalaxmi", or any phrasing outside the list.
The data was there; the question simply failed a regex, and the agent then
correctly reported that it had no records. That is the single most common
wrong answer this product gives.

So the model gets tools and decides for itself what to fetch, iteratively —
which is what makes a general chat assistant feel general.

Two rules hold the security:

1. `db` and `tenant_id` are closed over by `build_tools`. They are NOT
   parameters the model can supply. The model chooses which question to ask;
   it can never choose whose data to ask it of.
2. Every row carries a `ref` that resolves to a real record, so the answer can
   still be cited and checked. A tool that returned prose would break that.

Everything here is plain SQL. No model calls: these are the hands, not the
head.
"""

from __future__ import annotations

import uuid
from typing import Any

from google.genai import types
from sqlalchemy import func, or_, select

from app.models.catalog import Item
from app.models.finance import Invoice, Payment
from app.models.ingestion import Interaction
from app.models.orders import Order, OrderLine
from app.models.party import Party
from app.services.clock import business_today
from app.services.query_tool import DECLARATION as QUERY_DECLARATION
from app.services.query_tool import QueryError, run_query
from app.services.sql import not_in_subquery

def _query(db, tenant_id, spec: dict) -> dict:
    """A rejected query is an answer the model can act on, not an exception."""
    try:
        return run_query(db, tenant_id, spec)
    except QueryError as exc:
        return {"error": str(exc), "rows": []}


# Enough to answer with, small enough that six calls do not blow the context.
LIMIT = 25


def _party_rows(db, tenant_id, name: str | None, limit: int = LIMIT):
    stmt = select(Party).where(Party.tenant_id == tenant_id)
    if name:
        like = f"%{name.strip().lower()}%"
        stmt = stmt.where(func.lower(Party.name).like(like))
    return db.execute(stmt.limit(limit)).scalars().all()


def build_tools(db, tenant_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Bind the lookups to one tenant and hand back what the model may call."""

    def find_parties(name: str = "") -> dict:
        rows = _party_rows(db, tenant_id, name or None)
        return {"rows": [
            {"ref": f"P{p.id}", "name": p.name, "city": p.city,
             "phone": p.phone, "kind": p.kind, "credit_days": p.credit_days}
            for p in rows
        ]}

    def outstanding(party: str = "") -> dict:
        stmt = (
            select(Party.id, Party.name, func.sum(Invoice.amount))
            .join(Invoice, Invoice.party_id == Party.id)
            .where(Invoice.tenant_id == tenant_id, Invoice.status == "open")
            .group_by(Party.id, Party.name)
            .order_by(func.sum(Invoice.amount).desc())
        )
        if party:
            stmt = stmt.where(func.lower(Party.name).like(f"%{party.strip().lower()}%"))
        rows = db.execute(stmt.limit(LIMIT)).all()
        return {"rows": [
            {"ref": f"P{pid}", "party": name, "outstanding": float(total or 0)}
            for pid, name, total in rows
        ], "total": float(sum((r[2] or 0) for r in rows))}

    def overdue(days: int = 0) -> dict:
        today = business_today()
        stmt = (
            select(Invoice, Party.name)
            .join(Party, Party.id == Invoice.party_id)
            .where(Invoice.tenant_id == tenant_id, Invoice.status == "open",
                   Invoice.due_date < today)
            .order_by(Invoice.due_date)
        )
        rows = db.execute(stmt.limit(LIMIT)).all()
        out = []
        for inv, party_name in rows:
            age = (today - inv.due_date).days if inv.due_date else None
            if days and age is not None and age < days:
                continue
            out.append({"ref": f"I{inv.id}", "party": party_name,
                        "invoice_no": inv.invoice_no, "amount": float(inv.amount or 0),
                        "due_date": str(inv.due_date), "days_overdue": age})
        return {"rows": out}

    def orders(party: str = "", status: str = "", undispatched: bool = False,
               side: str = "") -> dict:
        stmt = (
            select(Order, Party.name)
            .outerjoin(Party, Party.id == Order.party_id)
            .where(Order.tenant_id == tenant_id)
            .order_by(Order.order_date.desc().nullslast())
        )
        if party:
            stmt = stmt.where(func.lower(Party.name).like(f"%{party.strip().lower()}%"))
        if status:
            stmt = stmt.where(Order.status == status.strip().lower())
        # "What have I bought" and "what have I sold" are the same table read
        # from either end: an order against a supplier is a purchase, against
        # a customer a sale. Without this the model was asked about purchases,
        # found no tool that mentioned them, and said it had no such records —
        # while the orders were sitting there under a supplier party.
        if side:
            wanted = "supplier" if side.strip().lower().startswith(("purchas", "buy", "supplier")) else "customer"
            stmt = stmt.where(Party.kind == wanted)
        if undispatched:
            from app.models.orders import Dispatch
            stmt = stmt.where(not_in_subquery(
                Order.id,
                select(Dispatch.order_id).where(Dispatch.tenant_id == tenant_id),
            ))
        rows = db.execute(stmt.limit(LIMIT)).all()
        out = []
        for order, party_name in rows:
            lines = db.execute(
                select(OrderLine).where(OrderLine.order_id == order.id).limit(6)
            ).scalars().all()
            items = [
                {"item": ln.raw_description, "quantity": float(ln.quantity or 0),
                 "unit": ln.unit, "rate": float(ln.rate or 0)}
                for ln in lines
            ]
            # A one-line summary alongside the detail. The citation shows the
            # summary; the model still sees every line to answer from.
            total_qty = sum(i["quantity"] for i in items)
            unit = next((i["unit"] for i in items if i["unit"]), "")
            out.append({
                "ref": f"O{order.id}", "party": party_name,
                "order_no": order.order_no, "status": order.status,
                "date": str(order.order_date or ""),
                "summary": (f"{len(items)} item{'s' if len(items) != 1 else ''}"
                            + (f", {total_qty:g} {unit}".rstrip() if total_qty else "")),
                "lines": items,
            })
        return {"rows": out}

    def payments(party: str = "") -> dict:
        stmt = (
            select(Payment, Party.name)
            .outerjoin(Party, Party.id == Payment.party_id)
            .where(Payment.tenant_id == tenant_id)
            .order_by(Payment.received_on.desc())
        )
        if party:
            stmt = stmt.where(func.lower(Party.name).like(f"%{party.strip().lower()}%"))
        rows = db.execute(stmt.limit(LIMIT)).all()
        return {"rows": [
            {"ref": f"Y{pay.id}", "party": name, "amount": float(pay.amount or 0),
             "mode": pay.mode, "received_on": str(pay.received_on or ""),
             "reference": pay.reference}
            for pay, name in rows
        ]}

    def rate_history(party: str = "", item: str = "") -> dict:
        stmt = (
            select(OrderLine, Party.name, Order.order_date)
            .join(Order, Order.id == OrderLine.order_id)
            .outerjoin(Party, Party.id == Order.party_id)
            .where(OrderLine.tenant_id == tenant_id, OrderLine.rate.isnot(None))
            .order_by(Order.order_date.desc())
        )
        if party:
            stmt = stmt.where(func.lower(Party.name).like(f"%{party.strip().lower()}%"))
        if item:
            like = f"%{item.strip().lower()}%"
            stmt = stmt.outerjoin(Item, Item.id == OrderLine.item_id).where(
                or_(func.lower(OrderLine.raw_description).like(like),
                    func.lower(Item.name).like(like))
            )
        rows = db.execute(stmt.limit(LIMIT * 2)).all()
        # One row per distinct (party, item, rate, date). Four identical lines
        # of "Arihant Garments, Rs 105/meter, 2026-07-22" is four order lines
        # of the same order, and citing all four teaches the owner nothing
        # while making the answer look broken.
        seen: set[tuple] = set()
        out = []
        for line, name, on in rows:
            key = (name, line.raw_description, float(line.rate or 0), str(on or ""))
            if key in seen:
                continue
            seen.add(key)
            out.append({"ref": f"L{line.id}", "party": name,
                        "item": line.raw_description, "rate": float(line.rate or 0),
                        "unit": line.unit, "date": str(on or "")})
            if len(out) >= LIMIT:
                break
        return {"rows": out}

    def search_messages(query: str, party: str = "") -> dict:
        """Full-text over the tenant's own messages. There is no vector index,
        so this is Postgres text search: good on names and codes, poor on
        paraphrase. The model is told as much in the system prompt."""
        stmt = select(Interaction).where(Interaction.tenant_id == tenant_id)
        terms = [t for t in (query or "").split() if len(t) > 2][:6]
        if terms:
            stmt = stmt.where(or_(*[
                func.lower(Interaction.body).like(f"%{t.lower()}%") for t in terms
            ]))
        if party:
            stmt = stmt.where(func.lower(Interaction.sender).like(f"%{party.strip().lower()}%"))
        rows = db.execute(
            stmt.order_by(Interaction.occurred_at.desc()).limit(LIMIT)
        ).scalars().all()
        return {"rows": [
            {"ref": f"M{m.id}", "sender": m.sender, "when": str(m.occurred_at or ""),
             "text": (m.body or "")[:140]}
            for m in rows
        ]}

    def _decl(name, description, properties, required=()):
        return types.FunctionDeclaration(
            name=name, description=description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    k: types.Schema(
                        type=types.Type.BOOLEAN if v == "bool"
                        else types.Type.INTEGER if v == "int"
                        else types.Type.STRING,
                        description=d,
                    )
                    for k, (v, d) in properties.items()
                },
                required=list(required),
            ),
        )

    return {
        "find_parties": {"run": find_parties, "declaration": _decl(
            "find_parties",
            "List customers and suppliers on record. Omit name to list all of them. "
            "Use this first when unsure whether a name the owner mentioned exists.",
            {"name": ("str", "Part of a party name. Leave empty to list all.")})},
        "outstanding": {"run": outstanding, "declaration": _decl(
            "outstanding",
            "How much each party currently owes, largest first. Omit party for everyone.",
            {"party": ("str", "Part of a party name. Leave empty for all parties.")})},
        "overdue": {"run": overdue, "declaration": _decl(
            "overdue",
            "Open invoices past their due date, oldest first, with days overdue.",
            {"days": ("int", "Only invoices at least this many days overdue. 0 for all.")})},
        "orders": {"run": orders, "declaration": _decl(
            "orders",
            "Orders with their line items, including amounts. This is also how "
            "purchases and sales are answered: an order against a supplier is a "
            "purchase, against a customer it is a sale — pass side='purchases' or "
            "side='sales'. Filter by party, by status "
            "(draft/confirmed/dispatched/cancelled), or undispatched=true for orders "
            "with no dispatch recorded.",
            {"party": ("str", "Part of a party name."),
             "status": ("str", "Order status to filter by."),
             "side": ("str", "'purchases' for supplier orders, 'sales' for customer orders."),
             "undispatched": ("bool", "True for orders with no dispatch recorded.")})},
        "payments": {"run": payments, "declaration": _decl(
            "payments",
            "Payments received, most recent first, with mode (cash/upi/neft/cheque) and reference.",
            {"party": ("str", "Part of a party name.")})},
        "rate_history": {"run": rate_history, "declaration": _decl(
            "rate_history",
            "What was charged for something previously, newest first. Use for "
            "'what rate did I give' and 'what did they pay last time'.",
            {"party": ("str", "Part of a party name."),
             "item": ("str", "Part of an item name or code.")})},
        # The general one. Everything above answers a question we predicted;
        # this answers the ones we did not, without letting a model near SQL.
        "query_records": {
            "run": lambda **kwargs: _query(db, tenant_id, kwargs),
            "declaration": QUERY_DECLARATION,
        },
        "search_messages": {"run": search_messages, "declaration": _decl(
            "search_messages",
            "Keyword search over the owner's own messages. Matches literal words, "
            "not meaning, so search for names, codes and numbers rather than "
            "paraphrases. Use when the structured lookups have not answered it.",
            {"query": ("str", "Words likely to appear literally in the message."),
             "party": ("str", "Restrict to messages from a sender.")},
            required=("query",))},
    }
