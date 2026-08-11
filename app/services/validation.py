"""Deterministic checks on what the model read.

Rules verify; the model reads. An extraction that reconciles arithmetically
against a party we know, in a unit this business uses, is trustworthy at a
lower model confidence than one that does not — and one that fails a money
check is not trustworthy at any confidence.

Every rule returns pass, fail, or not_applicable, and `not_applicable` is
recorded rather than folded into `pass`. The difference matters: "the total
adds up" and "there was no total to check" are different states, and silently
treating the second as the first is how a validation layer becomes decoration.
"""

from __future__ import annotations

import re
import statistics
import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.models.catalog import Quality
from app.models.orders import Order, OrderLine
from app.models.party import Party
from app.services.clock import business_today

PASS = "pass"
FAIL = "fail"
NA = "not_applicable"

# Trade arithmetic is quoted to the rupee but rounded in conversation, and a
# stated total often excludes GST. 2% absorbs the rounding without absorbing a
# transposed digit.
TOLERANCE_PCT = 2.0

# Below this many past observations, "the usual rate for this party" is not a
# fact about the business, it is a fact about a small sample.
MIN_HISTORY = 3
RATE_BAND_PCT = 40.0

# Fields whose failure means money could be wrong. These never auto-commit.
MONEY_FIELDS = frozenset({"amount", "rate", "balance"})


@dataclass
class RuleResult:
    rule: str
    status: str
    detail: str = ""
    # Which extracted fields this rule was judging, so a failure can point the
    # review screen at the thing to fix.
    fields: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return self.status == FAIL

    @property
    def touches_money(self) -> bool:
        return bool(MONEY_FIELDS.intersection(self.fields))


def _num(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - unparseable is simply absent
        return None


def _within(a: Decimal, b: Decimal, pct: float = TOLERANCE_PCT) -> bool:
    if b == 0:
        return a == 0
    return abs((a - b) / b) * 100 <= Decimal(str(pct))


def _lines(fields: dict[str, Any]) -> list[dict[str, Any]]:
    raw = fields.get("lines")
    if isinstance(raw, list) and raw:
        return [line for line in raw if isinstance(line, dict)]
    if any(fields.get(k) is not None for k in ("quality", "quantity", "rate")):
        return [fields]
    return []


# --- arithmetic -----------------------------------------------------------


def check_line_arithmetic(fields: dict[str, Any]) -> RuleResult:
    """quantity x rate reconciles to a stated line or order total."""
    lines = _lines(fields)
    total = _num(fields.get("amount")) or _num(fields.get("total"))
    if not lines or total is None:
        return RuleResult("line_arithmetic", NA, "no stated total to reconcile against",
                          ("amount",))

    computed = Decimal(0)
    for line in lines:
        quantity = _num(line.get("quantity"))
        rate = _num(line.get("rate")) or _num(fields.get("rate"))
        if quantity is None or rate is None:
            return RuleResult("line_arithmetic", NA,
                              "a line is missing quantity or rate", ("quantity", "rate"))
        computed += quantity * rate

    if _within(computed, total):
        return RuleResult("line_arithmetic", PASS,
                          f"{computed:.0f} reconciles to {total:.0f}",
                          ("quantity", "rate", "amount"))
    return RuleResult(
        "line_arithmetic", FAIL,
        f"lines compute to {computed:.0f} but the message says {total:.0f}",
        ("quantity", "rate", "amount"),
    )


def check_quantity_sum(fields: dict[str, Any]) -> RuleResult:
    """Line quantities add up to any stated overall quantity."""
    lines = _lines(fields)
    stated = _num(fields.get("total_quantity"))
    if len(lines) < 2 or stated is None:
        return RuleResult("quantity_sum", NA, "no overall quantity stated", ("quantity",))

    computed = Decimal(0)
    for line in lines:
        quantity = _num(line.get("quantity"))
        if quantity is None:
            return RuleResult("quantity_sum", NA, "a line has no quantity", ("quantity",))
        computed += quantity

    if _within(computed, stated, 0.5):
        return RuleResult("quantity_sum", PASS, f"{computed} = {stated}", ("quantity",))
    return RuleResult("quantity_sum", FAIL,
                      f"lines total {computed} but the message says {stated}", ("quantity",))


def check_payment_not_over_outstanding(
    db, tenant_id: uuid.UUID, party_id, fields: dict[str, Any]
) -> RuleResult:
    """A payment should not exceed what the party actually owes.

    Overpayment happens — advances, round figures — so this is a soft signal
    rather than an error, but a payment several times the outstanding balance
    is usually a misread digit.
    """
    amount = _num(fields.get("amount"))
    if amount is None or party_id is None:
        return RuleResult("payment_vs_outstanding", NA,
                          "no amount or no party to compare against", ("amount",))

    from app.services.ledger import outstanding_by_party  # local: avoids a cycle

    rows = {
        r["party_id"]: r for r in outstanding_by_party(db, tenant_id, business_today(), 45)
    }
    position = rows.get(party_id if isinstance(party_id, uuid.UUID) else uuid.UUID(str(party_id)))
    if position is None:
        return RuleResult("payment_vs_outstanding", NA,
                          "nothing outstanding on record for this party", ("amount",))

    outstanding = Decimal(str(position["outstanding"]))
    if amount <= outstanding * Decimal("1.05"):
        return RuleResult("payment_vs_outstanding", PASS,
                          f"{amount:.0f} against {outstanding:.0f} outstanding", ("amount",))
    return RuleResult(
        "payment_vs_outstanding", FAIL,
        f"{amount:.0f} is more than the {outstanding:.0f} outstanding",
        ("amount",),
    )


# --- referential ----------------------------------------------------------


def check_party_exists(db, tenant_id: uuid.UUID, party_id) -> RuleResult:
    if party_id is None:
        return RuleResult("party_known", FAIL, "no party could be resolved", ("party",))
    try:
        resolved = party_id if isinstance(party_id, uuid.UUID) else uuid.UUID(str(party_id))
    except (TypeError, ValueError):
        return RuleResult("party_known", FAIL, "party reference is not readable", ("party",))

    exists = db.execute(
        select(Party.id).where(Party.tenant_id == tenant_id, Party.id == resolved)
    ).scalars().first()
    if exists:
        return RuleResult("party_known", PASS, "", ("party",))
    return RuleResult("party_known", FAIL, "party is not on file", ("party",))


def check_unit(profile, fields: dict[str, Any]) -> RuleResult:
    """The unit is one this business actually quotes in."""
    vocab = (profile.vocabulary if profile else {}) or {}
    known = {u.strip().lower() for u in vocab.get("quantity_units", []) if u}
    if not known:
        return RuleResult("unit_known", NA, "profile lists no units", ("unit",))

    units = {
        str(u).strip().lower()
        for u in [fields.get("unit"), *(line.get("unit") for line in _lines(fields))]
        if u
    }
    if not units:
        return RuleResult("unit_known", NA, "no unit stated", ("unit",))

    # "m"/"mtr" are the same unit as "meter" to everyone in the trade.
    aliases = {"m": "meter", "mtr": "meter", "mtrs": "meter", "mts": "meter",
               "kgs": "kg", "pcs": "piece", "pc": "piece", "than": "thaan"}
    unknown = {u for u in units if aliases.get(u, u) not in known and u not in known}
    if not unknown:
        return RuleResult("unit_known", PASS, "", ("unit",))
    return RuleResult("unit_known", FAIL,
                      f"unit(s) this business does not use: {', '.join(sorted(unknown))}",
                      ("unit",))


def check_quality_format(db, tenant_id: uuid.UUID, profile, fields: dict[str, Any]) -> RuleResult:
    """A quality code either exists already or matches the profile's format."""
    codes = [
        str(c).strip()
        for c in [fields.get("quality"), *(line.get("quality") for line in _lines(fields))]
        if c
    ]
    if not codes:
        return RuleResult("quality_known", NA, "no quality named", ("quality",))

    known = {
        c.lower()
        for c in db.execute(
            select(Quality.code).where(Quality.tenant_id == tenant_id)
        ).scalars().all()
    }
    pattern = ((profile.vocabulary if profile else {}) or {}).get("quality_code_regex")
    compiled = None
    if pattern:
        try:
            compiled = re.compile(pattern)
        except re.error:
            compiled = None

    unrecognised = [
        c for c in codes
        if c.lower() not in known and not (compiled and compiled.match(c))
    ]
    if not unrecognised:
        return RuleResult("quality_known", PASS, "", ("quality",))
    if not known and not compiled:
        # A brand new tenant has no catalogue yet; that is not a failure.
        return RuleResult("quality_known", NA, "no catalogue to check against", ("quality",))
    return RuleResult("quality_known", FAIL,
                      f"quality not on file: {', '.join(unrecognised)}", ("quality",))


# --- historical -----------------------------------------------------------


def check_rate_band(db, tenant_id: uuid.UUID, party_id, fields: dict[str, Any]) -> RuleResult:
    """The rate sits within what this party has historically paid."""
    rates = [
        _num(r) for r in
        [fields.get("rate"), *(line.get("rate") for line in _lines(fields))]
    ]
    rates = [r for r in rates if r is not None]
    if not rates or party_id is None:
        return RuleResult("rate_band", NA, "no rate or no party", ("rate",))

    # The party brief already holds this, incrementally maintained. Falling
    # back to a query keeps the rule working for a party whose brief has not
    # been built yet.
    party = db.get(Party, party_id if isinstance(party_id, uuid.UUID)
                   else uuid.UUID(str(party_id)))
    band = ((party.attributes or {}).get("brief") or {}).get("rate_band") if party else None
    if band and band.get("observations", 0) >= MIN_HISTORY and band.get("typical"):
        typical = Decimal(str(band["typical"]))
        outliers = [r for r in rates if not _within(r, typical, RATE_BAND_PCT)]
        if not outliers:
            return RuleResult("rate_band", PASS,
                              f"within this party's usual {typical:.0f}", ("rate",))
        return RuleResult(
            "rate_band", FAIL,
            f"rate {outliers[0]:.0f} is far from this party's usual {typical:.0f}",
            ("rate",),
        )

    history = [
        float(r) for r in db.execute(
            select(OrderLine.rate)
            .join(Order, Order.id == OrderLine.order_id)
            .where(
                OrderLine.tenant_id == tenant_id,
                Order.party_id == party_id,
                OrderLine.rate.isnot(None),
            )
            .order_by(OrderLine.created_at.desc())
            .limit(50)
        ).scalars().all()
    ]
    if len(history) < MIN_HISTORY:
        return RuleResult("rate_band", NA,
                          f"only {len(history)} past rates for this party", ("rate",))

    typical = Decimal(str(statistics.median(history)))
    outliers = [r for r in rates if not _within(r, typical, RATE_BAND_PCT)]
    if not outliers:
        return RuleResult("rate_band", PASS, f"within band of {typical:.0f}", ("rate",))
    return RuleResult(
        "rate_band", FAIL,
        f"rate {outliers[0]:.0f} is far from this party's usual {typical:.0f}",
        ("rate",),
    )


# --- the pass -------------------------------------------------------------


def validate(db, tenant_id: uuid.UUID, profile, record: dict[str, Any]) -> list[RuleResult]:
    """Run every rule that applies to this record type."""
    fields = record.get("fields") or {}
    record_type = record.get("record_type")
    party_id = (record.get("resolution") or {}).get("party_id")

    results = [check_party_exists(db, tenant_id, party_id)]

    if record_type in ("order", "enquiry", "quote"):
        results += [
            check_line_arithmetic(fields),
            check_quantity_sum(fields),
            check_unit(profile, fields),
            check_quality_format(db, tenant_id, profile, fields),
            check_rate_band(db, tenant_id, party_id, fields),
        ]
    elif record_type == "payment":
        results.append(check_payment_not_over_outstanding(db, tenant_id, party_id, fields))
    elif record_type == "complaint":
        results.append(check_unit(profile, fields))

    return results


def as_dicts(results: list[RuleResult]) -> list[dict[str, Any]]:
    return [{**asdict(r), "fields": list(r.fields)} for r in results]


def failed_fields(results: list[RuleResult]) -> set[str]:
    """Fields implicated by a failing rule — what the owner should look at."""
    return {field for r in results if r.failed for field in r.fields}


def money_rule_failed(results: list[RuleResult]) -> bool:
    return any(r.failed and r.touches_money for r in results)
