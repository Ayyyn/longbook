"""Party memory: what this business knows about a customer.

`Party` is a ledger row. A trader's actual memory of a customer is richer and
mostly unwritten — what they buy, what they pay, whether the cheque clears,
whether the last delivery had a complaint on it. The brief is that memory made
explicit so it can be fed back into the system.

Three constraints shape it:

* **Committed records only.** An unreviewed extraction is a proposal, not a
  fact, and a brief built from proposals would tell the owner things that are
  not true and then feed them back into the prompts that produce more of them.
* **Incremental.** Regenerating from the whole history on every commit is
  affordable today and not at 50 tenants and three years of data. The brief
  carries a watermark and only reads what changed.
* **Traceable.** Every claim names the records it came from, because the first
  question about anything surprising is "says who?".

It is used three ways: as party context in the Extractor's prompt, as the
historical input to validation's rate-band check, and as the material
DraftComposer writes a reminder from.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.catalog import Quality
from app.models.finance import Invoice, Payment
from app.models.ingestion import Extraction
from app.models.orders import Order, OrderLine
from app.models.party import Party

# Enough history to say something, few enough to stay current. A trader cares
# about the last handful of dealings, not the full three years.
TOP_QUALITIES = 6
RECENT_ORDERS = 20
BRIEF_VERSION = 2

# Statuses whose records are real. Anything else is a proposal.
_COMMITTED = ("auto_committed", "accepted", "corrected")


def _d(value: Any) -> float:
    return float(value or 0)


def _empty() -> dict[str, Any]:
    return {
        "version": BRIEF_VERSION,
        "buys": [],
        "rate_band": {},
        "payment_behaviour": {},
        "complaints": {"count": 0, "recent": []},
        "contact": {},
        "totals": {},
        "sources": {},
        "generated_at": None,
        "watermark": None,
    }


def _pending_free(model):
    """Rows the owner has confirmed. Mirrors the ledger's own exclusion."""
    from app.services.ledger import _confirmed

    return _confirmed(model)


def build_brief(db, tenant_id: uuid.UUID, party: Party, since: datetime | None = None
                ) -> dict[str, Any]:
    """Regenerate a party's brief, reading only what changed since `since`.

    `since` is the previous watermark. Aggregates that must cover all history
    (totals, rate band) are recomputed from the stored brief plus the new rows
    rather than re-read in full.
    """
    previous = dict(party.attributes.get("brief") or {}) if party.attributes else {}
    if previous.get("version") != BRIEF_VERSION:
        previous, since = {}, None  # the shape changed; rebuild from scratch

    brief = _empty()
    brief["watermark"] = datetime.utcnow().isoformat()
    brief["generated_at"] = brief["watermark"]

    order_where = [OrderLine.tenant_id == tenant_id, Order.party_id == party.id]
    if since:
        order_where.append(Order.created_at >= since)

    lines = db.execute(
        select(OrderLine, Order, Quality.code)
        .join(Order, Order.id == OrderLine.order_id)
        .outerjoin(Quality, Quality.id == OrderLine.quality_id)
        .where(*order_where, _pending_free(Order))
        .order_by(Order.order_date.desc().nullslast())
        .limit(RECENT_ORDERS * 4)
    ).all()

    # --- what they buy ---------------------------------------------------
    counts: dict[str, int] = dict(previous.get("_quality_counts") or {})
    rates: list[float] = list(previous.get("_rates") or [])
    order_ids: set[str] = set()

    for line, order, code in lines:
        name = code or line.raw_description
        if name:
            counts[name] = counts.get(name, 0) + 1
        if line.rate is not None:
            rates.append(_d(line.rate))
        order_ids.add(str(order.id))

    brief["_quality_counts"] = counts
    brief["_rates"] = rates[-100:]  # bounded, so the row cannot grow forever
    brief["buys"] = [
        {"quality": name, "times": times}
        for name, times in sorted(counts.items(), key=lambda kv: -kv[1])[:TOP_QUALITIES]
    ]

    if brief["_rates"]:
        band = brief["_rates"]
        brief["rate_band"] = {
            "low": round(min(band), 2),
            "typical": round(statistics.median(band), 2),
            "high": round(max(band), 2),
            "observations": len(band),
            # Direction of travel matters more than the number: a customer whose
            # rate is drifting down is negotiating harder, not buying more.
            "recent": round(statistics.median(band[-5:]), 2) if len(band) >= 5 else None,
        }

    # --- how they actually pay -------------------------------------------
    from app.services.ledger import party_positions

    positions = party_positions(db, tenant_id, date.today())
    position = positions.get(party.id)

    if position is not None:
        lags = [s.lag_days for s in position.settlements]
        brief["payment_behaviour"] = {
            "settlements": len(lags),
            "avg_days_to_settle": round(statistics.fmean(lags), 1) if lags else None,
            "worst_days": max(lags) if lags else None,
            "outstanding": _d(position.outstanding),
            "days_overdue": position.days_overdue(date.today()),
            "unapplied_credit": _d(position.unapplied_credit),
            "terms_days": party.credit_days or 0,
        }
        if lags and party.credit_days:
            average = statistics.fmean(lags)
            brief["payment_behaviour"]["versus_terms"] = (
                "on time" if average <= 0 else f"{average:.0f} days past terms"
            )

    modes = db.execute(
        select(Payment.mode, func.count())
        .where(Payment.tenant_id == tenant_id, Payment.party_id == party.id,
               Payment.mode.isnot(None), _pending_free(Payment))
        .group_by(Payment.mode)
        .order_by(func.count().desc())
    ).all()
    if modes:
        brief["payment_behaviour"]["modes"] = [
            {"mode": mode, "times": count} for mode, count in modes
        ]

    part_payments = db.execute(
        select(func.count())
        .select_from(Payment)
        .where(Payment.tenant_id == tenant_id, Payment.party_id == party.id,
               _pending_free(Payment))
    ).scalar_one()
    invoices = db.execute(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.tenant_id == tenant_id, Invoice.party_id == party.id)
    ).scalar_one()
    if invoices:
        brief["payment_behaviour"]["payments_per_invoice"] = round(
            part_payments / invoices, 2
        )

    # --- complaints -------------------------------------------------------
    complaints = db.execute(
        select(Extraction)
        .where(
            Extraction.tenant_id == tenant_id,
            Extraction.record_type == "complaint",
            Extraction.status.in_(_COMMITTED),
        )
        .order_by(Extraction.created_at.desc())
        .limit(5)
    ).scalars().all()
    mine = [
        c for c in complaints
        if str((c.resolved or {}).get("party_id") or "") == str(party.id)
    ]
    brief["complaints"] = {
        "count": len(mine),
        "recent": [
            {
                "when": c.created_at.date().isoformat() if c.created_at else None,
                "what": (c.payload or {}).get("notes")
                or (c.payload or {}).get("quality"),
                "extraction_id": str(c.id),
            }
            for c in mine
        ],
    }

    # --- who they are -----------------------------------------------------
    brief["contact"] = {
        "name": party.name,
        "phone": party.phone,
        "city": party.city,
        "credit_days": party.credit_days,
        "aliases": list(party.aliases or []),
    }

    totals = db.execute(
        select(func.count(func.distinct(Order.id)))
        .select_from(Order)
        .where(Order.tenant_id == tenant_id, Order.party_id == party.id)
    ).scalar_one()
    last_order = db.execute(
        select(func.max(Order.order_date))
        .where(Order.tenant_id == tenant_id, Order.party_id == party.id)
    ).scalar_one()
    brief["totals"] = {
        "orders": totals,
        "last_order_on": last_order.isoformat() if last_order else None,
        "days_since_last_order": (date.today() - last_order).days if last_order else None,
    }

    # --- traceability -----------------------------------------------------
    brief["sources"] = {
        "orders": sorted(order_ids)[:RECENT_ORDERS],
        "complaints": [c["extraction_id"] for c in brief["complaints"]["recent"]],
        "incremental_since": since.isoformat() if since else None,
    }
    return brief


def refresh_party(db, tenant_id: uuid.UUID, party_id: uuid.UUID) -> dict[str, Any]:
    """Regenerate one party's brief and store it on the row."""
    party = db.get(Party, party_id)
    if party is None:
        return {}

    stored = (party.attributes or {}).get("brief") or {}
    watermark = stored.get("watermark")
    since = None
    if watermark:
        try:
            since = datetime.fromisoformat(watermark)
        except ValueError:
            since = None

    brief = build_brief(db, tenant_id, party, since)
    party.attributes = {**(party.attributes or {}), "brief": brief}
    db.flush()
    return brief


def refresh_stale(db, tenant_id: uuid.UUID, older_than_minutes: int = 0) -> int:
    """Refresh every party whose brief is missing or older than the cutoff."""
    cutoff = datetime.utcnow() - timedelta(minutes=older_than_minutes)
    parties = db.execute(
        select(Party).where(Party.tenant_id == tenant_id)
    ).scalars().all()

    refreshed = 0
    for party in parties:
        brief = (party.attributes or {}).get("brief") or {}
        stamp = brief.get("generated_at")
        if stamp and brief.get("version") == BRIEF_VERSION:
            try:
                if datetime.fromisoformat(stamp) > cutoff:
                    continue
            except ValueError:
                pass
        refresh_party(db, tenant_id, party.id)
        refreshed += 1
    return refreshed


def as_prompt_context(brief: dict[str, Any]) -> str:
    """The brief compressed to what an extraction prompt can use.

    Deliberately terse: this rides along on every window, so it earns its
    tokens or it does not go.
    """
    if not brief:
        return ""
    parts = []
    buys = ", ".join(b["quality"] for b in brief.get("buys", [])[:4])
    if buys:
        parts.append(f"usually buys {buys}")
    band = brief.get("rate_band") or {}
    if band.get("typical"):
        parts.append(f"usual rate around {band['typical']:g}")
    behaviour = brief.get("payment_behaviour") or {}
    if behaviour.get("avg_days_to_settle") is not None:
        parts.append(f"settles in about {behaviour['avg_days_to_settle']:.0f} days")
    return "; ".join(parts)


def reminder_facts(brief: dict[str, Any]) -> dict[str, Any]:
    """What DraftComposer needs to write a reminder that sounds informed."""
    behaviour = brief.get("payment_behaviour") or {}
    return {
        "outstanding": behaviour.get("outstanding"),
        "days_overdue": behaviour.get("days_overdue"),
        "terms_days": behaviour.get("terms_days"),
        "usual_days_to_settle": behaviour.get("avg_days_to_settle"),
        "versus_terms": behaviour.get("versus_terms"),
        "last_order_on": (brief.get("totals") or {}).get("last_order_on"),
        "open_complaints": (brief.get("complaints") or {}).get("count", 0),
        "preferred_mode": (
            behaviour.get("modes", [{}])[0].get("mode") if behaviour.get("modes") else None
        ),
    }
