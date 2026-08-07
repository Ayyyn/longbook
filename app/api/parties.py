"""Party routes: the list, and everything known about one customer.

The detail page is the party brief — what they buy, what they pay, how they
actually behave versus the terms on paper — next to the ledger it is derived
from. Every claim is traceable, because the first question about anything
surprising is "says who?".
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.api.deps import Profile, TenantDB, TenantId
from app.models.orders import Order
from app.models.party import Party
from app.schemas.parties import PartyBrief, PartyDetail, PartyRow, PartySummary
from app.services.ledger import outstanding_by_party, party_ledger
from app.services.party_brief import refresh_party
from app.services.wa import wa_link

router = APIRouter()

DEFAULT_OVERDUE_DAYS = 45


def _overdue_days(profile) -> int:
    return int(((profile.rules if profile else {}) or {}).get(
        "overdue_days", DEFAULT_OVERDUE_DAYS))


@router.get("", response_model=PartySummary)
@router.get("/", response_model=PartySummary, include_in_schema=False)
def list_parties(
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    q: str | None = Query(None, description="name or phone"),
    overdue_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
) -> PartySummary:
    """Everyone, worst debt first — that is the order an owner scans in."""
    where = [Party.tenant_id == tid]
    if q:
        needle = f"%{q.strip().lower()}%"
        where.append(or_(func.lower(Party.name).like(needle), Party.phone.like(f"%{q.strip()}%")))

    parties = db.execute(select(Party).where(*where)).scalars().all()
    positions = {
        row["party_id"]: row
        for row in outstanding_by_party(db, tid, date.today(), _overdue_days(profile))
    }

    rows = []
    for party in parties:
        position = positions.get(party.id, {})
        if overdue_only and not position.get("is_overdue"):
            continue
        brief = (party.attributes or {}).get("brief") or {}
        rows.append(
            PartyRow(
                id=party.id,
                name=party.name,
                phone=party.phone,
                city=party.city,
                kind=party.kind,
                credit_days=party.credit_days,
                outstanding=position.get("outstanding", 0.0),
                days_overdue=position.get("days_overdue", 0),
                is_overdue=bool(position.get("is_overdue")),
                last_order_on=(brief.get("totals") or {}).get("last_order_on"),
                orders=(brief.get("totals") or {}).get("orders", 0),
            )
        )

    rows.sort(key=lambda r: (-r.days_overdue, -r.outstanding, r.name.lower()))
    return PartySummary(
        parties=rows[:limit],
        total=len(rows),
        total_outstanding=round(sum(r.outstanding for r in rows), 2),
        overdue_days=_overdue_days(profile),
    )


@router.get("/{party_id}", response_model=PartyDetail)
def party_detail(
    party_id: uuid.UUID,
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    refresh: bool = Query(False, description="regenerate the brief before returning"),
) -> PartyDetail:
    party = db.get(Party, party_id)
    if party is None:
        raise HTTPException(404, "Party not found.")

    brief = (party.attributes or {}).get("brief") or {}
    if refresh or not brief:
        brief = refresh_party(db, tid, party_id)

    as_of = date.today()
    statement = party_ledger(db, tid, party_id, as_of)
    positions = {
        row["party_id"]: row
        for row in outstanding_by_party(db, tid, as_of, _overdue_days(profile))
    }
    position = positions.get(party_id, {})

    orders = db.execute(
        select(Order)
        .where(Order.tenant_id == tid, Order.party_id == party_id)
        .order_by(Order.order_date.desc().nullslast(), Order.created_at.desc())
        .limit(25)
    ).scalars().all()

    link = None
    if party.phone and statement["closing_balance"] > 0:
        link = wa_link(party.phone, _reminder(party.name, statement["closing_balance"], brief))

    return PartyDetail(
        id=party.id,
        name=party.name,
        phone=party.phone,
        city=party.city,
        gstin=party.gstin,
        kind=party.kind,
        credit_days=party.credit_days,
        aliases=list(party.aliases or []),
        outstanding=position.get("outstanding", 0.0),
        days_overdue=position.get("days_overdue", 0),
        closing_balance=statement["closing_balance"],
        brief=PartyBrief(**_brief_out(brief)),
        entries=statement["entries"],
        orders=[
            {
                "id": str(o.id),
                "order_no": o.order_no,
                "status": o.status,
                "order_date": o.order_date,
                "promised_date": o.promised_date,
                "lines": len(o.lines),
                "pending_fields": (o.attributes or {}).get("pending_fields", []),
            }
            for o in orders
        ],
        reminder_link=link,
    )


def _brief_out(brief: dict) -> dict:
    """Drop the internal accumulators the brief carries for incremental work."""
    return {k: v for k, v in brief.items() if not k.startswith("_")}


def _reminder(name: str, balance: float, brief: dict) -> str:
    """A draft the owner edits and sends themselves.

    Uses the brief so it sounds like it came from someone who knows the
    customer, which is the difference between a reminder that gets a reply and
    one that gets ignored. The system never sends it.
    """
    from app.api.ledger import _rupees

    behaviour = (brief or {}).get("payment_behaviour") or {}
    lines = [f"Namaste {name},", ""]
    lines.append(f"Our records show {_rupees(balance)} outstanding.")

    days = behaviour.get("days_overdue") or 0
    if days > 0:
        lines.append(f"The oldest bill is {days} days past due.")
    if behaviour.get("preferred_mode"):
        lines.append(f"{behaviour['preferred_mode'].upper()} is fine as usual.")

    lines.append("")
    lines.append("Could you confirm when payment is expected? Thank you.")
    return "\n".join(lines)
