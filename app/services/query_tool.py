"""A general lookup the model can shape, without letting it write SQL.

The seven fixed tools answer the seven questions we thought of. "What is my
average order value by month", "which customers have I not heard from since
June", "share of purchases per supplier" are not among them, and a business
asking one of those gets told the records do not exist — which is untrue and
is the same failure as the keyword-matched retrieval this replaced.

The obvious fix is to let the model write SQL. That is also the fastest way to
leak one customer's ledger into another's answer: one prompt injection in an
uploaded WhatsApp message, one missing WHERE clause, and the isolation this
system enforces at the session layer is gone.

So the model composes a *structure* instead — entity, filters, grouping,
aggregate — and this module turns it into SQLAlchemy. Three properties make
that safe, and all three are enforced here rather than asked for:

1. **The tenant filter is added by us, always.** It is not a parameter and
   cannot be named, overridden or removed by anything the model emits.
2. **Only allow-listed columns exist.** A field not in ALLOWED is rejected
   rather than interpolated, so there is no string that reaches SQL.
3. **Read-only by construction.** The builder emits SELECT and nothing else;
   there is no code path here that writes.

The cost of that safety is expressiveness: no joins the caller did not plan
for, no subqueries, no arbitrary expressions. That is the right trade. A model
that cannot answer "average order value by month in Gujarati-speaking
districts" is a smaller problem than one that can read another business's
books.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from google.genai import types
from sqlalchemy import and_, func, or_, select

from app.models.finance import Invoice, Payment
from app.models.ingestion import Interaction
from app.models.orders import Order, OrderLine
from app.models.party import Party

MAX_ROWS = 60

# Entity -> (model, {exposed name: column}). Anything not here does not exist
# as far as a query is concerned.
ENTITIES: dict[str, tuple[Any, dict[str, Any]]] = {
    "parties": (Party, {
        "name": Party.name, "kind": Party.kind, "city": Party.city,
        "phone": Party.phone, "gstin": Party.gstin,
        "credit_days": Party.credit_days, "created_at": Party.created_at,
    }),
    "orders": (Order, {
        "order_no": Order.order_no, "status": Order.status,
        "order_date": Order.order_date, "promised_date": Order.promised_date,
        "party": Party.name, "party_kind": Party.kind, "city": Party.city,
    }),
    "order_lines": (OrderLine, {
        "item": OrderLine.raw_description, "quantity": OrderLine.quantity,
        "unit": OrderLine.unit, "rate": OrderLine.rate,
        "order_date": Order.order_date, "status": Order.status,
        "party": Party.name, "party_kind": Party.kind,
    }),
    "invoices": (Invoice, {
        "invoice_no": Invoice.invoice_no, "amount": Invoice.amount,
        "tax_amount": Invoice.tax_amount, "status": Invoice.status,
        "invoice_date": Invoice.invoice_date, "due_date": Invoice.due_date,
        "party": Party.name, "party_kind": Party.kind,
    }),
    "payments": (Payment, {
        "amount": Payment.amount, "mode": Payment.mode,
        "reference": Payment.reference, "received_on": Payment.received_on,
        "party": Party.name, "party_kind": Party.kind,
    }),
    "messages": (Interaction, {
        "sender": Interaction.sender, "occurred_at": Interaction.occurred_at,
        "channel": Interaction.channel, "body": Interaction.body,
    }),
}

# How each entity reaches Party, so "party" can be selected or filtered on
# without the model knowing anything about joins.
JOINS: dict[str, list[tuple[Any, Any]]] = {
    "orders": [(Party, Party.id == Order.party_id)],
    "order_lines": [(Order, Order.id == OrderLine.order_id),
                    (Party, Party.id == Order.party_id)],
    "invoices": [(Party, Party.id == Invoice.party_id)],
    "payments": [(Party, Party.id == Payment.party_id)],
}

OPS = {"=", "!=", ">", ">=", "<", "<=", "contains", "in", "is_null", "not_null"}
AGGREGATES = {"count", "sum", "avg", "min", "max"}


class QueryError(ValueError):
    """The shape asked for cannot be built. Handed back, never raised at a user."""


def _column(entity: str, field: str):
    columns = ENTITIES[entity][1]
    if field not in columns:
        raise QueryError(
            f"No field '{field}' on {entity}. Available: {', '.join(sorted(columns))}"
        )
    return columns[field]


def _condition(entity: str, spec: dict):
    column = _column(entity, str(spec.get("field", "")))
    op = str(spec.get("op", "=")).lower()
    if op not in OPS:
        raise QueryError(f"Unknown operator '{op}'. Use one of: {', '.join(sorted(OPS))}")
    value = spec.get("value")

    if op == "is_null":
        return column.is_(None)
    if op == "not_null":
        return column.isnot(None)
    if op == "contains":
        return func.lower(column).like(f"%{str(value).strip().lower()}%")
    if op == "in":
        values = value if isinstance(value, list) else [value]
        return column.in_(values)
    if op == "=":
        return column == value
    if op == "!=":
        # NULL never equals anything, so a plain != silently drops every row
        # with an empty value — the trap that has bitten this codebase before.
        return or_(column != value, column.is_(None))
    return {">": column > value, ">=": column >= value,
            "<": column < value, "<=": column <= value}[op]


def run_query(db, tenant_id: uuid.UUID, spec: dict) -> dict:
    """Build and run one read-only, tenant-scoped query from a structure."""
    entity = str(spec.get("entity", "")).lower()
    if entity not in ENTITIES:
        raise QueryError(
            f"No such thing as '{entity}'. Available: {', '.join(sorted(ENTITIES))}"
        )

    model, _columns = ENTITIES[entity]
    group_by = [g for g in (spec.get("group_by") or []) if g]
    aggregate = (spec.get("aggregate") or "").lower()
    agg_field = spec.get("aggregate_field")

    if aggregate and aggregate not in AGGREGATES:
        raise QueryError(f"Unknown aggregate '{aggregate}'.")

    selected: list[Any] = []
    labels: list[str] = []
    for field in group_by:
        selected.append(_column(entity, field))
        labels.append(field)

    if aggregate:
        if aggregate == "count":
            selected.append(func.count())
            labels.append("count")
        else:
            if not agg_field:
                raise QueryError(f"'{aggregate}' needs aggregate_field.")
            selected.append(getattr(func, aggregate)(_column(entity, agg_field)))
            labels.append(f"{aggregate}_{agg_field}")
    elif not group_by:
        # No grouping and no aggregate: return the fields asked for, or a
        # sensible handful rather than the whole row.
        wanted = [f for f in (spec.get("fields") or []) if f] or list(_columns)[:6]
        for field in wanted:
            selected.append(_column(entity, field))
            labels.append(field)

    stmt = select(*selected).select_from(model)
    for target, onclause in JOINS.get(entity, []):
        stmt = stmt.outerjoin(target, onclause)

    # The one condition nobody can remove.
    conditions = [model.tenant_id == tenant_id]
    for spec_where in (spec.get("where") or []):
        conditions.append(_condition(entity, spec_where))
    stmt = stmt.where(and_(*conditions))

    if group_by:
        stmt = stmt.group_by(*[_column(entity, f) for f in group_by])

    order_by = spec.get("order_by")
    if order_by:
        descending = bool(spec.get("descending", True))
        if order_by in labels:
            target = selected[labels.index(order_by)]
        else:
            target = _column(entity, order_by)
        stmt = stmt.order_by(target.desc() if descending else target.asc())

    limit = min(int(spec.get("limit") or 25), MAX_ROWS)
    rows = db.execute(stmt.limit(limit)).all()

    out = []
    for row in rows:
        record = {}
        for label, value in zip(labels, row):
            record[label] = _plain(value)
        out.append(record)
    return {"rows": out, "count": len(out)}


def _plain(value):
    """JSON-safe. Numerics arrive as Decimal, which serialises as a string and
    then reads to the model as text — "62.0000000000000000" rather than 62."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        as_float = float(value)
        return int(as_float) if as_float.is_integer() else round(as_float, 2)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (int, float, bool)):
        return value
    return str(value)


DECLARATION = types.FunctionDeclaration(
    name="query_records",
    description=(
        "Ask a shaped question of the business's records when the other lookups "
        "do not fit — totals per party, counts by month, averages, shares. "
        "Read-only.\n"
        "entity: parties | orders | order_lines | invoices | payments | messages.\n"
        "Fields by entity — parties: name, kind, city, phone, gstin, credit_days; "
        "orders: order_no, status, order_date, promised_date, party, party_kind, city; "
        "order_lines: item, quantity, unit, rate, order_date, status, party, party_kind; "
        "invoices: invoice_no, amount, tax_amount, status, invoice_date, due_date, party, party_kind; "
        "payments: amount, mode, reference, received_on, party, party_kind; "
        "messages: sender, occurred_at, channel, body.\n"
        "where: list of {field, op, value}; op is =, !=, >, >=, <, <=, contains, "
        "in, is_null or not_null.\n"
        "group_by: list of fields. aggregate: count|sum|avg|min|max with "
        "aggregate_field. order_by a field or the aggregate label, descending "
        "true/false, limit up to 60.\n"
        "Example — total invoiced per supplier: entity=invoices, "
        "group_by=[party], aggregate=sum, aggregate_field=amount, "
        "where=[{field: party_kind, op: '=', value: 'supplier'}]."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "entity": types.Schema(type=types.Type.STRING, description="What to read."),
            "where": types.Schema(
                type=types.Type.ARRAY,
                description="Filters, each {field, op, value}.",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "field": types.Schema(type=types.Type.STRING),
                        "op": types.Schema(type=types.Type.STRING),
                        "value": types.Schema(type=types.Type.STRING),
                    },
                ),
            ),
            "fields": types.Schema(
                type=types.Type.ARRAY, description="Fields to return when not grouping.",
                items=types.Schema(type=types.Type.STRING)),
            "group_by": types.Schema(
                type=types.Type.ARRAY, description="Fields to group by.",
                items=types.Schema(type=types.Type.STRING)),
            "aggregate": types.Schema(type=types.Type.STRING,
                                      description="count, sum, avg, min or max."),
            "aggregate_field": types.Schema(type=types.Type.STRING,
                                            description="Field the aggregate applies to."),
            "order_by": types.Schema(type=types.Type.STRING),
            "descending": types.Schema(type=types.Type.BOOLEAN),
            "limit": types.Schema(type=types.Type.INTEGER),
        },
        required=["entity"],
    ),
)
