"""Ledger and exception routes.

Every number here comes from `app/services/ledger.py`, which does no model
calls — the owner will check these against Tally and they have to survive that.

Note what is missing: `overdue_crossings` is not exposed. It consumes its own
watermark, so a screen that called it would silently eat the alerts the evening
digest is supposed to deliver. Screens get `outstanding` and read it themselves.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import Profile, TenantDB, TenantId
from app.models.party import Party
from app.schemas.ledger import (
    AgeingReport,
    Exceptions,
    OutstandingRow,
    OutstandingSummary,
    PartyLedger,
)
from app.services import exceptions as exception_rules
from app.services.ledger import ageing_buckets, outstanding_by_party, party_ledger, payment_trend
from app.services.wa import wa_link

router = APIRouter()

DEFAULT_OVERDUE_DAYS = 45
DEFAULT_RATE_DEVIATION_PCT = 20


def _rule(profile, key: str, fallback):
    return ((profile.rules if profile else {}) or {}).get(key, fallback)


@router.get("/outstanding", response_model=OutstandingSummary)
def outstanding(
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    as_of: date | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> OutstandingSummary:
    """Who owes what, oldest debt first."""
    as_of = as_of or date.today()
    overdue_days = int(_rule(profile, "overdue_days", DEFAULT_OVERDUE_DAYS))

    rows = outstanding_by_party(db, tid, as_of, overdue_days)
    return OutstandingSummary(
        as_of=as_of,
        overdue_days=overdue_days,
        total_outstanding=round(sum(r["outstanding"] for r in rows), 2),
        total_overdue=round(sum(r["outstanding"] for r in rows if r["is_overdue"]), 2),
        parties_overdue=sum(1 for r in rows if r["is_overdue"]),
        parties=[OutstandingRow(**row) for row in rows[:limit]],
    )


@router.get("/ageing", response_model=AgeingReport)
def ageing(
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    as_of: date | None = Query(None),
) -> AgeingReport:
    """Outstanding split by how far past due it is."""
    as_of = as_of or date.today()
    overdue_days = int(_rule(profile, "overdue_days", DEFAULT_OVERDUE_DAYS))

    buckets = ageing_buckets(db, tid, as_of, overdue_days)
    return AgeingReport(
        as_of=as_of,
        overdue_days=overdue_days,
        buckets=buckets,
        total=round(sum(buckets.values()), 2),
    )


@router.get("/exceptions", response_model=Exceptions)
def flagged_exceptions(
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    as_of: date | None = Query(None),
) -> Exceptions:
    """Everything worth interrupting the owner about, in one call."""
    as_of = as_of or date.today()
    threshold = float(_rule(profile, "rate_deviation_pct", DEFAULT_RATE_DEVIATION_PCT))

    deviations = exception_rules.rate_deviations(db, tid, threshold, as_of)
    stalled = exception_rules.stalled_orders(db, tid, as_of)
    slowing = payment_trend(db, tid)
    drafts = exception_rules.stale_drafts(db, tid, as_of)

    return Exceptions(
        as_of=as_of,
        rate_deviations=deviations,
        stalled_orders=stalled,
        slowing_payers=slowing,
        stale_drafts=drafts,
        total=len(deviations) + len(stalled) + len(slowing),
    )


@router.get("/party/{party_id}", response_model=PartyLedger)
def party_statement(
    party_id: uuid.UUID,
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    as_of: date | None = Query(None),
) -> PartyLedger:
    """Every document behind one party's balance, plus a drafted reminder.

    The reminder is a `wa.me` link the owner taps and sends themselves. The
    system never sends it — see BUILD_PROMPT constraint 1.
    """
    as_of = as_of or date.today()
    party = db.get(Party, party_id)
    if party is None:
        raise HTTPException(404, "Party not found.")

    overdue_days = int(_rule(profile, "overdue_days", DEFAULT_OVERDUE_DAYS))
    statement = party_ledger(db, tid, party_id, as_of)

    rows = {r["party_id"]: r for r in outstanding_by_party(db, tid, as_of, overdue_days)}
    position = rows.get(party_id)
    days_overdue = position["days_overdue"] if position else 0

    link = None
    if party.phone and statement["closing_balance"] > 0:
        link = wa_link(party.phone, _reminder_text(party.name, statement["closing_balance"]))

    return PartyLedger(
        party_id=party_id,
        party_name=party.name,
        as_of=as_of,
        closing_balance=statement["closing_balance"],
        days_overdue=days_overdue,
        credit_days=party.credit_days,
        phone=party.phone,
        entries=statement["entries"],
        reminder_link=link,
    )


def _reminder_text(name: str, balance: float) -> str:
    """A plain draft. The owner edits it before sending, and usually should."""
    return (
        f"Namaste {name}, "
        f"our records show {_rupees(balance)} outstanding. "
        "Could you confirm when payment is expected? Thank you."
    )


def _rupees(amount: float) -> str:
    """Indian digit grouping: 1,25,000 not 125,000."""
    whole = f"{int(round(amount)):d}"
    if len(whole) <= 3:
        return f"Rs {whole}"
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return f"Rs {','.join(parts)},{tail}"
