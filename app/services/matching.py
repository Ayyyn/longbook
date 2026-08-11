"""Party matching helpers. Cheap deterministic passes before any model call.

The Resolver walks these in order — alias, phone, trigram — and only asks the
model to choose when the shortlist is still ambiguous. Every function here is
pure SQL on purpose: a wrongly-attributed payment is the worst failure this
system has, so the cheap passes must be reproducible and explainable.

`tenant_id` is passed explicitly rather than leaning on the session guard in
`app/db.py`, because the trigram pass is raw SQL and the guard cannot see
inside it.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.models.party import Party

# Case-folded membership test over the aliases array. Postgres cannot index
# this, but a tenant's party list is thousands of rows, not millions.
_ALIAS_HIT = text("EXISTS (SELECT 1 FROM unnest(party.aliases) AS a WHERE lower(a) = :alias)")

_TRIGRAM_SHORTLIST = text(
    """
    SELECT id,
           name,
           GREATEST(
               similarity(name, :q),
               COALESCE((SELECT max(similarity(a, :q)) FROM unnest(aliases) AS a), 0)
           ) AS score
    FROM party
    WHERE tenant_id = :tenant_id
    ORDER BY score DESC, name ASC
    LIMIT :limit
    """
)


@dataclass(frozen=True)
class PartyMatch:
    """A trigram candidate. `.id` and `.score` are the Resolver's contract."""

    id: uuid.UUID
    name: str
    score: float


def store_phone(phone: str | None) -> str | None:
    """The canonical form an owner's number is STORED in: digits only.

    Formatting is where this went wrong. "98250 66554" was stored verbatim
    because that is how the owner typed it, and every lookup that stripped
    the query to digits then failed to match it — including token recovery,
    which answers identically whether it found you or not. The owner waits
    for an email that will never arrive and support cannot find them.

    Any leading country code is kept; matching is done on the last ten
    digits, which is what identifies an Indian mobile.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits or None


def normalize_phone(phone: str | None) -> str | None:
    """Last 10 digits, which is what identifies an Indian mobile.

    The same number arrives as `+919876543210`, `91 98765 43210` and
    `9876543210` depending on whether it came from a contact card, a chat
    export header, or someone typing it into a message.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else None


def exact_alias_match(db: Session, tenant_id: uuid.UUID | str, name: str) -> Party | None:
    """Exact match on Party.name or any entry in Party.aliases (case-folded)."""
    needle = (name or "").strip().lower()
    if not needle:
        return None

    stmt = (
        select(Party)
        .where(
            Party.tenant_id == tenant_id,
            or_(func.lower(Party.name) == needle, _ALIAS_HIT.bindparams(alias=needle)),
        )
        .order_by(Party.created_at.asc())  # oldest wins if a name was duplicated
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def phone_match(db: Session, tenant_id: uuid.UUID | str, phone: str | None) -> Party | None:
    """Match on the last 10 digits of a stored phone number."""
    last10 = normalize_phone(phone)
    if not last10:
        return None

    stored = func.right(func.regexp_replace(Party.phone, r"\D", "", "g"), 10)
    stmt = (
        select(Party)
        .where(Party.tenant_id == tenant_id, Party.phone.isnot(None), stored == last10)
        .order_by(Party.created_at.asc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def shortlist_parties(
    db: Session,
    tenant_id: uuid.UUID | str,
    name: str,
    limit: int = 5,
    threshold: float = 0.3,
) -> list[PartyMatch]:
    """pg_trgm similarity shortlist. Requires: CREATE EXTENSION pg_trgm;
    Returns objects with .id and .score."""
    needle = (name or "").strip()
    if not needle:
        return []

    rows = db.execute(
        _TRIGRAM_SHORTLIST,
        {"q": needle, "tenant_id": str(tenant_id), "limit": limit},
    ).all()

    # Thresholding in Python rather than with the `%` operator keeps the result
    # independent of the session's pg_trgm.similarity_threshold GUC — the
    # Resolver's 0.85 auto-accept cutoff has to mean the same thing everywhere.
    return [
        PartyMatch(id=r.id, name=r.name, score=float(r.score))
        for r in rows
        if float(r.score) >= threshold
    ]
