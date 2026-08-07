"""Field-level gating: commit what is certain, ask only for what is not.

Record-level gating throws away most of the signal. A payment carrying a party,
a UTR and a date but no amount was queued in its entirety, and the owner was
handed an empty form to re-enter four things when three of them were already
right. Here the record is committed with the amount left blank, and the owner
is asked one question.

Two rules keep that safe:

* A record with any pending field is a `draft` and is excluded from ledger
  totals, so a half-known payment can never become a number the owner acts on.
* A field is only "certain" if it is present, was not implicated in a failing
  validation rule, and the record cleared its confidence bar. Absence is never
  treated as certainty.

There is no per-field score from the model — it reports one confidence per
record. Inventing per-field numbers from it would be dressing a guess up as a
measurement, so certainty here is derived from things that are actually known:
presence, validation, and the record's own confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from app.services.validation import MONEY_FIELDS, RuleResult, failed_fields

# What a record must carry before it is worth writing at all. Anything not
# listed is optional: its absence is not a question worth asking the owner.
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "order": ("party", "quantity"),
    "payment": ("party", "amount"),
    "dispatch": ("party",),
    "enquiry": ("party",),
    "complaint": ("party",),
}

# Fields worth asking about when missing, even though a record can exist
# without them. Ordered by how often an owner actually needs them.
USEFUL_FIELDS: dict[str, tuple[str, ...]] = {
    "order": ("quality", "rate", "unit", "delivery_date"),
    "payment": ("mode", "reference", "received_on"),
    "dispatch": ("lr_no", "transporter", "dispatched_on"),
    "enquiry": ("quality", "quantity", "rate"),
    "complaint": ("quality", "quantity"),
}


@dataclass
class Gate:
    """What may be committed now, and what must be asked."""

    committable: bool
    pending: list[str] = dc_field(default_factory=list)
    reasons: dict[str, str] = dc_field(default_factory=dict)

    @property
    def blocks_money(self) -> bool:
        return bool(MONEY_FIELDS.intersection(self.pending))


def _present(fields: dict[str, Any], name: str) -> bool:
    """Whether a field actually carries a value.

    `quantity` counts as present if any line has one — a multi-line order does
    not repeat it at the top level.
    """
    value = fields.get(name)
    if value not in (None, "", [], {}):
        return True
    if name in ("quantity", "quality", "rate"):
        lines = fields.get("lines")
        if isinstance(lines, list):
            return any(
                isinstance(line, dict) and line.get(name) not in (None, "", [], {})
                for line in lines
            )
    return False


def gate_record(
    record: dict[str, Any],
    validations: list[RuleResult],
    *,
    confidence: float,
    floor: float,
) -> Gate:
    """Decide which fields are certain enough to write."""
    record_type = record.get("record_type") or ""
    fields = record.get("fields") or {}
    party_id = (record.get("resolution") or {}).get("party_id")

    suspect = failed_fields(validations)
    pending: list[str] = []
    reasons: dict[str, str] = {}

    def flag(name: str, why: str) -> None:
        if name not in pending:
            pending.append(name)
            reasons[name] = why

    for name in REQUIRED_FIELDS.get(record_type, ()):
        if name == "party":
            if not party_id:
                flag("party", "could not be matched to anyone on file")
            continue
        if not _present(fields, name):
            flag(name, "not stated in the conversation")

    # Deliberately no rule for "money field that is simply absent". A rate not
    # yet agreed or an order with no total is ordinary trade, and asking about
    # every one would refill the queue with questions the owner cannot answer.
    # Absent money only blocks when the record type requires it — a payment
    # with no amount, above — because then there is no record without it.

    for name in suspect:
        if name == "party" and party_id:
            continue
        if _present(fields, name) or name in REQUIRED_FIELDS.get(record_type, ()):
            flag(name, "a validation check disagreed with this")

    # Below the floor the model itself is unsure, and it cannot say which part
    # it is unsure about — so everything the record asserts is up for review.
    if confidence < floor:
        for name in (*REQUIRED_FIELDS.get(record_type, ()), *USEFUL_FIELDS.get(record_type, ())):
            if _present(fields, name) or name in REQUIRED_FIELDS.get(record_type, ()):
                flag(name, f"low confidence ({confidence:.2f})")

    return Gate(committable=not pending, pending=pending, reasons=reasons)


def strip_pending(fields: dict[str, Any], pending: list[str]) -> dict[str, Any]:
    """Remove values the owner has not confirmed.

    A pending field is blanked rather than kept, so nothing downstream can read
    an unconfirmed number and treat it as fact.
    """
    stripped = {k: v for k, v in fields.items() if k not in pending}
    if "lines" in stripped and isinstance(stripped["lines"], list):
        stripped["lines"] = [
            {k: v for k, v in line.items() if k not in pending} if isinstance(line, dict)
            else line
            for line in stripped["lines"]
        ]
    return stripped
