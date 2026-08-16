"""Proposing party merges, and carrying them out once confirmed.

Real party lists collect duplicates. "Arihant Garments" and "Arihant Garments -
Nilesh" are one customer written down twice — once from a Tally import and
once from the name on a WhatsApp thread — and until they are merged, half that
customer's orders sit under a name the owner does not think of as a customer,
their outstanding is split across two rows, and the ageing on both is wrong.

Nothing here merges automatically, and that is the whole design. Two businesses
with similar names are common — "Shah Textiles" and "Shah Textiles & Sons" may
genuinely be father and son trading separately — and a wrong merge is far
harder to undo than a missed one: the records are combined, the aliases are
combined, and no record of which row each came from survives. So this proposes,
the owner confirms, and a rejection is remembered so the same pair is never
suggested twice.

Detection is deterministic on purpose. A model asked "are these the same
business?" will answer yes far more often than it should, and confidently.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update

from app.models.finance import Invoice, Payment
from app.models.ledger_state import LedgerWatermark
from app.models.orders import Order
from app.models.party import Party
from app.services.matching import normalize_phone

# Everything that points at a party and must be moved when two become one.
OWNED = ((Order, "party_id"), (Invoice, "party_id"), (Payment, "party_id"),
         (LedgerWatermark, "party_id"))

# Words that carry no identity: two firms differing only by these are the same
# firm written twice.
NOISE = {"pvt", "private", "ltd", "limited", "llp", "co", "company", "and",
         "the", "inc", "corporation", "corp", "enterprises", "enterprise"}


def _tokens(name: str | None) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {w for w in words if w not in NOISE and len(w) > 1}


@dataclass
class MergeSuggestion:
    """One proposed merge, with the reason stated in the owner's terms."""

    primary_id: uuid.UUID
    duplicate_id: uuid.UUID
    primary_name: str
    duplicate_name: str
    reason: str
    confidence: float
    primary_records: int
    duplicate_records: int

    @property
    def suggestion_id(self) -> str:
        return f"{self.primary_id}:{self.duplicate_id}"


def _record_count(db, tenant_id: uuid.UUID, party_id: uuid.UUID) -> int:
    total = 0
    for model, column in OWNED:
        total += db.execute(
            select(func.count()).select_from(model).where(
                model.tenant_id == tenant_id, getattr(model, column) == party_id)
        ).scalar_one()
    return total


def _rejected(party: Party) -> set[str]:
    return set((party.attributes or {}).get("merge_rejected") or [])


def suggest_merges(db, tenant_id: uuid.UUID, limit: int = 20) -> list[MergeSuggestion]:
    """Pairs worth asking about. Never merges anything."""
    parties = db.execute(
        select(Party).where(Party.tenant_id == tenant_id)
    ).scalars().all()

    out: list[MergeSuggestion] = []
    for i, a in enumerate(parties):
        for b in parties[i + 1:]:
            if str(b.id) in _rejected(a) or str(a.id) in _rejected(b):
                continue

            reason = None
            confidence = 0.0
            a_tokens, b_tokens = _tokens(a.name), _tokens(b.name)
            phone_a, phone_b = normalize_phone(a.phone), normalize_phone(b.phone)

            if phone_a and phone_a == phone_b:
                reason = f"Both have the phone number {a.phone}."
                confidence = 0.95
            elif a_tokens and a_tokens == b_tokens:
                reason = "The names are the same apart from punctuation."
                confidence = 0.9
            elif a_tokens and b_tokens and (a_tokens < b_tokens or b_tokens < a_tokens):
                longer = b.name if len(b_tokens) > len(a_tokens) else a.name
                shorter = a.name if longer == b.name else b.name
                reason = f"“{longer}” is “{shorter}” with something added."
                confidence = 0.75
            elif a.gstin and a.gstin == b.gstin:
                reason = f"Both have GSTIN {a.gstin}."
                confidence = 0.95

            if not reason:
                continue

            # The one with more history is the one to keep: fewer rows move,
            # and the owner recognises the name their records already use.
            a_count = _record_count(db, tenant_id, a.id)
            b_count = _record_count(db, tenant_id, b.id)
            primary, duplicate = (a, b) if a_count >= b_count else (b, a)
            p_count, d_count = (a_count, b_count) if primary is a else (b_count, a_count)

            out.append(MergeSuggestion(
                primary_id=primary.id, duplicate_id=duplicate.id,
                primary_name=primary.name, duplicate_name=duplicate.name,
                reason=reason, confidence=confidence,
                primary_records=p_count, duplicate_records=d_count,
            ))

    out.sort(key=lambda s: s.confidence, reverse=True)
    return out[:limit]


def reject_merge(db, tenant_id: uuid.UUID, primary_id: uuid.UUID,
                 duplicate_id: uuid.UUID) -> None:
    """Remember that these two are different, so we stop asking."""
    for keep, other in ((primary_id, duplicate_id), (duplicate_id, primary_id)):
        party = db.get(Party, keep)
        if party is None or party.tenant_id != tenant_id:
            continue
        attributes = dict(party.attributes or {})
        rejected = set(attributes.get("merge_rejected") or [])
        rejected.add(str(other))
        attributes["merge_rejected"] = sorted(rejected)
        party.attributes = attributes
    db.flush()


def merge_parties(db, tenant_id: uuid.UUID, primary_id: uuid.UUID,
                  duplicate_id: uuid.UUID) -> dict:
    """Move everything to the primary, keep the old name as an alias, delete it.

    The duplicate's name survives as an alias rather than being discarded: it
    is what the owner's messages actually say, and the Resolver matches on
    aliases, so dropping it would send every future record about that name
    back to review.
    """
    if primary_id == duplicate_id:
        raise ValueError("A party cannot be merged into itself.")

    primary = db.get(Party, primary_id)
    duplicate = db.get(Party, duplicate_id)
    if primary is None or duplicate is None:
        raise ValueError("One of those parties no longer exists.")
    if primary.tenant_id != tenant_id or duplicate.tenant_id != tenant_id:
        raise ValueError("Those parties do not both belong to this business.")

    moved = 0
    for model, column in OWNED:
        result = db.execute(
            update(model)
            .where(model.tenant_id == tenant_id, getattr(model, column) == duplicate_id)
            .values(**{column: primary_id})
        )
        moved += result.rowcount or 0

    known = {a.lower() for a in (primary.aliases or [])} | {primary.name.lower()}
    extra = [n for n in [duplicate.name, *(duplicate.aliases or [])]
             if n and n.lower() not in known]
    if extra:
        primary.aliases = [*(primary.aliases or []), *extra]

    # Fill only what is missing. An import is new information, not a more
    # authoritative version of what is already there.
    primary.phone = primary.phone or duplicate.phone
    primary.city = primary.city or duplicate.city
    primary.gstin = primary.gstin or duplicate.gstin
    if duplicate.credit_days and not primary.credit_days:
        primary.credit_days = duplicate.credit_days

    db.delete(duplicate)
    db.flush()
    return {"merged_into": str(primary_id), "records_moved": moved,
            "aliases_added": extra}
