"""Commit / review-queue boundary.

Single place where an agent decision becomes a business record. Nothing else
in the codebase should write to order/payment/party tables from extraction.

Two rules shape everything here:

* Confidence gates writes. Anything the pipeline is not sure about — a low
  score, an unresolved party, a quality code nobody has seen before — becomes a
  review-queue row instead of a business record. A wrong order in the system is
  more expensive than one the owner has to tap through.
* Every committed record keeps its receipt. The `Extraction` row survives the
  commit and points at what it produced, so the owner can trace any number on
  the dashboard back to the WhatsApp line it came from.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from app.models.catalog import Item
from app.models.finance import Payment
from app.models.ingestion import Extraction
from app.models.observability import AgentRun
from app.models.orders import Dispatch, Order, OrderLine
from app.models.party import Party
from app.models.tenant import BusinessProfile
from app.services.vocabulary import default_unit

AUTO_COMMIT_FLOOR = 0.85
MAX_EXAMPLES = 40

# Records the owner reviews and the system stores. "enquiry" is deliberately
# not in here: it has no business table, it is context for the next order.
_WRITABLE = {"order", "payment", "dispatch"}


# --- field coercion -------------------------------------------------------
# Extraction returns strings shaped by however the message was typed. These
# never raise: a field we cannot read is a field for the owner to fill in.


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _num(value: Any) -> Decimal | None:
    """`"1,25,000"`, `"₹ 62"`, `"62/-"` all mean a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    cleaned = "".join(c for c in str(value) if c.isdigit() or c in ".-")
    cleaned = cleaned.rstrip("-.")
    try:
        return Decimal(cleaned) if cleaned else None
    except InvalidOperation:
        return None


def _date(value: Any, fallback: date | None = None) -> date | None:
    """Trade messages say "friday tak" as often as they say a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = _text(value)
    if not s:
        return fallback
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return fallback


def _jsonable(value: Any) -> Any:
    """Make a value safe for a JSONB column.

    Party ids arrive as `UUID` from a correction and as `str` from the
    Resolver, and dates arrive both ways too. Normalising on the way in keeps
    the receipt readable and stops one code path from poisoning the column.
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _lines(fields: dict[str, Any]) -> list[dict[str, Any]]:
    """One message can carry several items; a flat message carries one."""
    raw = fields.get("lines")
    if isinstance(raw, list) and raw:
        return [ln for ln in raw if isinstance(ln, dict)]
    if any(fields.get(k) is not None for k in ("quality", "quantity", "rate", "description")):
        return [fields]
    return []


# --- helpers --------------------------------------------------------------


def _uuid_or_none(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _interaction_id(state: dict[str, Any]) -> uuid.UUID | None:
    return _uuid_or_none((state.get("interaction") or {}).get("id"))


def _occurred_on(state: dict[str, Any]) -> date | None:
    raw = (state.get("interaction") or {}).get("occurred_at")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    parsed = _date(raw)
    return parsed


def _source(state: dict[str, Any]) -> tuple[str, str | None]:
    channel = (state.get("interaction") or {}).get("channel") or "manual"
    source = "whatsapp" if str(channel).startswith("whatsapp") else str(channel)
    iid = _interaction_id(state)
    return source, (str(iid) if iid else None)


def _refresh_brief(db, tenant_id, party_id) -> None:
    """Keep the party brief current as records land.

    Best-effort: a brief that fails to regenerate must never roll back the
    record that triggered it, because the record is the thing that matters.
    """
    if not party_id:
        return
    try:
        from app.services.party_brief import refresh_party

        refresh_party(db, tenant_id, _uuid_or_none(party_id))
    except Exception:  # noqa: BLE001 - memory is an optimisation, not a guarantee
        pass


def _pending(state: dict[str, Any]) -> list[str]:
    return list(state.get("pending_fields") or [])


def _status(state: dict[str, Any]) -> str:
    """A record with anything outstanding is queued even though it was written.

    This is the whole point of field-level gating: the row exists so the owner
    can see it, and it sits in the queue so they are asked the one question
    that is actually open.
    """
    return "needs_review" if _pending(state) else "auto_committed"


def _mark(row, state: dict[str, Any], extraction_id: uuid.UUID | None = None) -> None:
    """Record on the business row what is still unconfirmed.

    Stored in `attributes` rather than a new column on five tables — that bag
    exists for exactly this. Ledger reads consult it, so a half-known payment
    cannot become a number the owner acts on.
    """
    pending = _pending(state)
    attributes = dict(getattr(row, "attributes", None) or {})
    if pending:
        attributes["pending_fields"] = pending
        attributes["pending_reasons"] = state.get("pending_reasons") or {}
    else:
        attributes.pop("pending_fields", None)
        attributes.pop("pending_reasons", None)
    if extraction_id:
        attributes["extraction_id"] = str(extraction_id)
    row.attributes = attributes


def _record_extraction(
    db,
    state: dict[str, Any],
    *,
    status: str,
    committed_type: str | None = None,
    committed_id: uuid.UUID | None = None,
) -> Extraction:
    """The receipt. Written on every path — committed, queued, or discarded."""
    extraction = state.get("extraction") or {}
    resolution = dict(state.get("resolution") or {})

    if state.get("flags"):
        resolution["flags"] = state["flags"]
    if state.get("pending_reasons"):
        resolution["pending_reasons"] = state["pending_reasons"]

    row = Extraction(
        tenant_id=state.get("tenant_id"),
        interaction_id=_interaction_id(state),
        trace_id=_uuid_or_none(state.get("trace_id")),
        window_id=_uuid_or_none(state.get("window_id")),
        source_message_ids=[str(i) for i in (state.get("source_message_ids") or [])],
        record_type=extraction.get("record_type"),
        payload=_jsonable(extraction.get("fields", {}) or {}),
        resolved=_jsonable(resolution),
        confidence=_num(extraction.get("confidence")),
        reason=extraction.get("reason") or "",
        status=status,
        committed_type=committed_type,
        committed_id=committed_id,
        validations=_jsonable(state.get("validations") or []),
        pending_fields=_pending(state),
    )
    db.add(row)
    db.flush()
    return row


def _resolve_quality(
    db, tenant_id, code: str | None, confidence: float, source: str, source_ref: str | None
) -> tuple[Item | None, bool]:
    """Find the quality, or mint it when we are confident enough to.

    Returns (quality, needs_review). A code nobody has seen before is either a
    new article or a mangled reading of an old one — at low confidence that
    distinction is exactly what the owner should make, not us.
    """
    if not code:
        return None, False

    existing = db.execute(
        select(Item).where(
            Item.tenant_id == tenant_id, func.lower(Item.code) == code.lower()
        )
    ).scalars().first()
    if existing:
        return existing, False

    if confidence < AUTO_COMMIT_FLOOR:
        return None, True

    quality = Item(
        tenant_id=tenant_id, code=code, name=code, source=source, source_ref=source_ref
    )
    db.add(quality)
    db.flush()
    return quality, False


# --- the three entry points ----------------------------------------------


def commit_record(db, state: dict[str, Any]) -> dict[str, Any]:
    """Map an extraction onto business records and insert them.

    Anything that turns out to be unsafe to write is handed to
    `queue_for_review` instead, so callers never have to second-guess this.
    """
    extraction = state.get("extraction") or {}
    record_type = extraction.get("record_type")
    fields = extraction.get("fields", {}) or {}
    confidence = float(extraction.get("confidence") or 0.0)
    tenant_id = state.get("tenant_id")
    source, source_ref = _source(state)

    if record_type == "noise":
        row = _record_extraction(db, state, status="rejected")
        return {"status": "discarded", "extraction_id": str(row.id)}

    if record_type not in _WRITABLE:
        # Enquiries and anything unrecognised are kept as context, not records.
        row = _record_extraction(db, state, status="auto_committed")
        return {"status": "logged", "record_type": record_type, "extraction_id": str(row.id)}

    party_id = (state.get("resolution") or {}).get("party_id")
    if not party_id:
        return queue_for_review(db, state, flags=["unresolved_party"])

    if record_type == "order":
        return _commit_order(db, state, fields, confidence, tenant_id, party_id, source, source_ref)
    if record_type == "payment":
        return _commit_payment(db, state, fields, tenant_id, party_id, source, source_ref)
    return _commit_dispatch(db, state, fields, tenant_id, party_id, source, source_ref)


def _commit_order(
    db, state, fields, confidence, tenant_id, party_id, source, source_ref
) -> dict[str, Any]:
    # Read once: the unit a business quotes in is profile-driven, and the
    # alternative is a hardcoded textile default on every line.
    profile = db.execute(
        select(BusinessProfile).where(BusinessProfile.tenant_id == tenant_id)
    ).scalars().first()
    lines = _lines(fields)
    if not lines and not _pending(state):
        return queue_for_review(db, state, flags=["order_without_lines"])

    # Resolve every item first: one unknown code sends the whole order to
    # review rather than committing a half-mapped order the owner has to unpick.
    resolved: list[tuple[dict[str, Any], Item | None]] = []
    for line in lines:
        quality, needs_review = _resolve_quality(
            db, tenant_id, _text(line.get("quality")), confidence, source, source_ref
        )
        if needs_review:
            return queue_for_review(
                db, state, flags=[f"unknown_quality({_text(line.get('quality'))})"]
            )
        resolved.append((line, quality))

    order = Order(
        tenant_id=tenant_id,
        party_id=party_id,
        order_no=_text(fields.get("order_no")),
        # Draft until a human confirms it — see app/models/orders.py.
        status="draft",
        order_date=_date(fields.get("order_date"), _occurred_on(state)),
        promised_date=_date(fields.get("delivery_date") or fields.get("promised_date")),
        notes=_text(fields.get("notes")),
        source=source,
        source_ref=source_ref,
    )
    db.add(order)
    db.flush()

    for line, quality in resolved:
        db.add(
            OrderLine(
                tenant_id=tenant_id,
                order_id=order.id,
                item_id=quality.id if quality else None,
                raw_description=_text(line.get("description") or line.get("quality")),
                quantity=_num(line.get("quantity")),
                # No textile default. If the message did not say a unit and
                # the profile has none, the unit is simply unknown — better
                # blank than metres of bearings.
                unit=_text(line.get("unit")) or default_unit(profile),
                rate=_num(line.get("rate")),
            )
        )

    db.flush()
    row = _record_extraction(
        db, state, status=_status(state), committed_type="order", committed_id=order.id
    )
    _mark(order, state, row.id)
    _refresh_brief(db, tenant_id, party_id)
    return {
        "status": "committed",
        "record_type": "order",
        "id": str(order.id),
        "lines": len(resolved),
        "extraction_id": str(row.id),
    }


def _commit_payment(db, state, fields, tenant_id, party_id, source, source_ref) -> dict[str, Any]:
    amount = _num(fields.get("amount"))
    # A missing amount is only acceptable when field-level gating has already
    # decided to ask the owner for it. Otherwise there is nothing to write.
    if (amount is None or amount <= 0) and "amount" not in _pending(state):
        return queue_for_review(db, state, flags=["missing_amount"])

    payment = Payment(
        tenant_id=tenant_id,
        party_id=party_id,
        amount=amount,
        mode=_text(fields.get("mode")),
        reference=_text(fields.get("reference") or fields.get("utr")),
        received_on=_date(fields.get("received_on") or fields.get("date"), _occurred_on(state)),
        cheque_date=_date(fields.get("cheque_date")),
        source=source,
        source_ref=source_ref,
    )
    db.add(payment)
    db.flush()

    row = _record_extraction(
        db, state, status=_status(state), committed_type="payment", committed_id=payment.id
    )
    _mark(payment, state, row.id)
    _refresh_brief(db, tenant_id, party_id)
    return {
        "status": "committed",
        "record_type": "payment",
        "id": str(payment.id),
        "extraction_id": str(row.id),
    }


def _commit_dispatch(db, state, fields, tenant_id, party_id, source, source_ref) -> dict[str, Any]:
    order_no = _text(fields.get("order_no"))
    order_id = None
    if order_no:
        order_id = db.execute(
            select(Order.id).where(Order.tenant_id == tenant_id, Order.order_no == order_no)
        ).scalars().first()

    dispatch = Dispatch(
        tenant_id=tenant_id,
        order_id=order_id,
        challan_no=_text(fields.get("challan_no")),
        transporter=_text(fields.get("transporter")),
        lr_no=_text(fields.get("lr_no")),
        dispatched_on=_date(fields.get("dispatched_on"), _occurred_on(state)),
        source=source,
        source_ref=source_ref,
    )
    db.add(dispatch)
    db.flush()

    row = _record_extraction(
        db, state, status=_status(state), committed_type="dispatch", committed_id=dispatch.id
    )
    _mark(dispatch, state, row.id)
    return {
        "status": "committed",
        "record_type": "dispatch",
        "id": str(dispatch.id),
        "extraction_id": str(row.id),
    }


def queue_for_review(
    db, state: dict[str, Any], flags: list[str] | None = None
) -> dict[str, Any]:
    """Persist an Extraction row with status='needs_review'."""
    if flags:
        state = {**state, "flags": [*(state.get("flags") or []), *flags]}
    row = _record_extraction(db, state, status="needs_review")
    return {
        "status": "needs_review",
        "extraction_id": str(row.id),
        "record_type": row.record_type,
        "flags": (row.resolved or {}).get("flags", []),
    }


_COMMITTED_MODELS = {"order": Order, "payment": Payment, "dispatch": Dispatch}


def _existing_record(db, extraction: Extraction):
    """The business row a partial commit already wrote, if there is one."""
    model = _COMMITTED_MODELS.get(extraction.committed_type or "")
    if model is None or not extraction.committed_id:
        return None
    return db.get(model, extraction.committed_id)


def _complete_record(db, extraction, row, record_type, fields, party_id) -> dict[str, Any]:
    """Fill in the fields the owner has now confirmed, in place.

    Only the fields that were pending are written — the rest were already
    committed and the owner has not been asked about them. Clearing
    `pending_fields` is what readmits the record to the ledger.
    """
    pending = set(extraction.pending_fields or [])
    if party_id is not None and hasattr(row, "party_id"):
        row.party_id = party_id

    if record_type == "payment":
        if "amount" in pending and _num(fields.get("amount")) is not None:
            row.amount = _num(fields.get("amount"))
        row.mode = row.mode or _text(fields.get("mode"))
        row.reference = row.reference or _text(fields.get("reference") or fields.get("utr"))
        row.received_on = row.received_on or _date(fields.get("received_on"))
    elif record_type == "order":
        row.order_no = row.order_no or _text(fields.get("order_no"))
        row.promised_date = row.promised_date or _date(fields.get("delivery_date"))
        # A single-line order can have its quantity or rate answered directly.
        if row.lines and len(row.lines) == 1:
            line = row.lines[0]
            if "quantity" in pending and _num(fields.get("quantity")) is not None:
                line.quantity = _num(fields.get("quantity"))
            if "rate" in pending and _num(fields.get("rate")) is not None:
                line.rate = _num(fields.get("rate"))
            if "unit" in pending and _text(fields.get("unit")):
                line.unit = _text(fields.get("unit"))
    elif record_type == "dispatch":
        row.lr_no = row.lr_no or _text(fields.get("lr_no"))
        row.transporter = row.transporter or _text(fields.get("transporter"))
        row.challan_no = row.challan_no or _text(fields.get("challan_no"))

    attributes = dict(row.attributes or {})
    attributes.pop("pending_fields", None)
    attributes.pop("pending_reasons", None)
    row.attributes = attributes

    db.flush()
    return {
        "status": "committed",
        "record_type": record_type,
        "id": str(row.id),
        "completed": sorted(pending),
    }


def accept_correction(db, extraction_id, corrected: dict[str, Any]) -> dict[str, Any]:
    """Owner corrected a queued item. Commit it AND append the corrected pair
    to BusinessProfile.examples so the tenant's extraction improves.

    `corrected` is the owner's version of the extraction:
        {"record_type": "order", "fields": {...}, "party_id": "...",
         "party_name": "Ashok Textiles"}
    Anything it omits falls back to what the agent originally proposed.
    """
    extraction = db.get(Extraction, extraction_id)
    if extraction is None:
        raise LookupError(f"extraction {extraction_id} not found")

    original_fields = extraction.payload or {}
    original_resolved = extraction.resolved or {}

    record_type = corrected.get("record_type") or extraction.record_type
    fields = corrected.get("fields") if corrected.get("fields") is not None else original_fields
    party_id = corrected.get("party_id") or original_resolved.get("party_id")

    # The owner naming a party the Resolver could not find is the one case
    # where a correction creates a Party — never the pipeline on its own.
    if not party_id and corrected.get("party_name"):
        party = Party(
            tenant_id=extraction.tenant_id,
            name=corrected["party_name"].strip(),
            source="manual",
            source_ref=str(extraction.id),
        )
        db.add(party)
        db.flush()
        party_id = party.id

    interaction = {
        "id": extraction.interaction_id,
        "channel": original_resolved.get("channel", "whatsapp_export"),
        "occurred_at": original_resolved.get("occurred_at"),
    }
    state = {
        "tenant_id": extraction.tenant_id,
        "trace_id": extraction.trace_id,
        "interaction": interaction,
        # A human vouched for these fields; they clear the confidence gate.
        "extraction": {"record_type": record_type, "fields": fields, "confidence": 1.0,
                       "reason": ""},
        "resolution": {**original_resolved, "party_id": party_id, "method": "human"},
    }

    # A partially-committed record already exists; the owner is answering the
    # one field that was pending, not creating a second copy of the record.
    existing = _existing_record(db, extraction)
    if existing is not None:
        result = _complete_record(db, extraction, existing, record_type, fields, party_id)
    else:
        result = commit_record(db, state)

    was_edited = fields != original_fields or record_type != extraction.record_type
    extraction.status = "corrected" if was_edited else "accepted"
    extraction.record_type = record_type
    extraction.payload = _jsonable(fields)
    extraction.resolved = _jsonable({**original_resolved, "party_id": party_id})
    extraction.pending_fields = []
    if result.get("id"):
        extraction.committed_type = result.get("record_type")
        extraction.committed_id = uuid.UUID(result["id"])

    # An order the owner has read and accepted is no longer a draft.
    if result.get("record_type") == "order" and result.get("id"):
        order = db.get(Order, uuid.UUID(result["id"]))
        if order is not None:
            order.status = "confirmed"

    _mark_human_override(db, extraction, extraction.trace_id)
    if was_edited:
        _harvest_example(db, extraction, record_type, fields)

    db.flush()
    return {**result, "extraction_id": str(extraction.id), "status": extraction.status}


def _mark_human_override(db, extraction: Extraction, trace_id: uuid.UUID | None) -> None:
    """Flag the agent runs behind this decision — this is the override rate the
    Agent Activity screen reports and the submission evidence measures."""
    if not trace_id:
        return
    runs = db.execute(
        select(AgentRun).where(
            AgentRun.tenant_id == extraction.tenant_id,
            AgentRun.trace_id == trace_id,
        )
    ).scalars().all()
    for run in runs:
        run.human_override = True
        run.reviewed_at = datetime.utcnow()


def _harvest_example(db, extraction: Extraction, record_type: str, fields: dict) -> None:
    """Append the (input, corrected_output) pair to the tenant's profile.

    This is how per-tenant accuracy compounds: the Extractor few-shots on these,
    so every correction the owner makes buys back some of the next week's
    review queue.
    """
    profile = db.execute(
        select(BusinessProfile).where(BusinessProfile.tenant_id == extraction.tenant_id)
    ).scalars().first()
    if profile is None:
        return

    from app.models.ingestion import Interaction  # local: avoids an import cycle at module load

    body = None
    if extraction.interaction_id:
        interaction = db.get(Interaction, extraction.interaction_id)
        body = interaction.body if interaction else None
    if not body:
        return

    example = {"input": body, "output": {"record_type": record_type, "fields": fields}}
    kept = [e for e in (profile.examples or []) if e.get("input") != body]
    # Reassigned, not mutated — SQLAlchemy only notices JSONB changes on assignment.
    profile.examples = [*kept, example][-MAX_EXAMPLES:]
