"""Triage — decides what may be written and what must be asked.

Deliberately rule-first, model-second. Rules are auditable and free; the model
is only consulted when rules are inconclusive. This is the same
exception-triage shape as reconciliation break resolution.

Three inputs, not one:

* **Validation** (app/services/validation.py) — deterministic checks on what
  the model read. Passing them earns a record the benefit of the doubt at a
  lower stated confidence; failing a money check forfeits it at any confidence.
* **Confidence**, weighted by what it would cost to be wrong. A large payment
  needs more certainty than a small enquiry, because the two are not
  symmetrically recoverable.
* **Field-level gating** (app/services/gating.py) — the outcome is no longer
  commit-or-queue for the whole record. Most records commit partially and ask
  about one field.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision
from app.services.gating import gate_record
from app.services.validation import as_dicts, money_rule_failed, validate

AUTO_COMMIT_FLOOR = 0.85

# What "high value" means before a profile says otherwise. An order or payment
# above this is worth an extra 0.05 of certainty; a mistake at this size is a
# phone call to a customer, not a quiet correction.
DEFAULT_HIGH_VALUE = 100_000
HIGH_VALUE_PREMIUM = 0.05

# An enquiry commits nothing to anybody — it is context for the next order, so
# it earns a lower bar rather than crowding the queue.
LOW_STAKES_TYPES = frozenset({"enquiry"})
LOW_STAKES_DISCOUNT = 0.15

# Passing every applicable deterministic check is real evidence, so it buys
# back some of the model's own hedging — but never enough to clear the floor
# from nothing.
VALIDATED_DISCOUNT = 0.10


def _record_value(payload: dict[str, Any]) -> float:
    """Roughly what this record is worth, for risk weighting."""
    amount = payload.get("amount")
    if isinstance(amount, (int, float)):
        return float(amount)

    quantity, rate = payload.get("quantity"), payload.get("rate")
    if isinstance(quantity, (int, float)) and isinstance(rate, (int, float)):
        return float(quantity) * float(rate)

    lines = payload.get("lines")
    if isinstance(lines, list):
        total = 0.0
        for line in lines:
            if not isinstance(line, dict):
                continue
            q, r = line.get("quantity"), line.get("rate")
            if isinstance(q, (int, float)) and isinstance(r, (int, float)):
                total += float(q) * float(r)
        return total
    return 0.0


class Triage(Agent):
    name = "triage"
    prompt_version = "v2"

    def run(self, payload: dict[str, Any]) -> Decision:
        conf = float(payload.get("confidence", 0))
        rules = (self.profile.rules if self.profile else {}) or {}
        record_type = payload.get("record_type")
        flags: list[str] = []

        if record_type == "noise":
            return Decision(output={"action": "discard"}, confidence=1.0)

        record = payload.get("record") or {}
        validations = validate(self.db, self.tenant_id, self.profile, record)
        validation_dicts = as_dicts(validations)
        applicable = [v for v in validations if v.status != "not_applicable"]
        all_passed = bool(applicable) and all(not v.failed for v in applicable)

        for result in validations:
            if result.failed:
                flags.append(f"{result.rule}: {result.detail}" if result.detail else result.rule)

        # --- the bar this record has to clear -----------------------------
        floor = AUTO_COMMIT_FLOOR
        value = _record_value(payload)
        high_value = float(rules.get("high_value_amount", DEFAULT_HIGH_VALUE))

        if record_type in LOW_STAKES_TYPES:
            floor -= LOW_STAKES_DISCOUNT
        if all_passed:
            floor -= VALIDATED_DISCOUNT

        if value >= high_value:
            # Applied last and as a floor, not an addend: passing the
            # deterministic checks is good evidence, but it must not buy a
            # large order past the extra certainty its size demands.
            floor = max(floor + HIGH_VALUE_PREMIUM,
                        AUTO_COMMIT_FLOOR + HIGH_VALUE_PREMIUM)
            flags.append(f"high_value({value:.0f})")

        gate = gate_record(record, validations, confidence=conf, floor=floor)

        # --- the rules that override everything ---------------------------
        # A defect claim leads to a credit note or a replacement, and neither
        # is a decision the system should take on the owner's behalf.
        if record_type == "complaint":
            return self._decide("review", conf, ["complaint", *flags], validation_dicts,
                                gate, "Complaints are always reviewed.")

        # Anything touching money that failed a check goes to a human whatever
        # the model said about it.
        if money_rule_failed(validations):
            return self._decide("review", conf, flags, validation_dicts, gate,
                                "A money check failed.")

        dev = payload.get("rate_deviation_pct")
        if dev is not None and abs(dev) > rules.get("rate_deviation_pct", 20):
            flags.append(f"rate_deviation({dev:.0f}%)")
        qty = payload.get("quantity")
        if qty is not None and qty <= 0:
            flags.append("implausible_quantity")
            return self._decide("review", conf, flags, validation_dicts, gate,
                                "Quantity is not plausible.")

        if conf < floor:
            flags.append(f"low_confidence({conf:.2f} < {floor:.2f})")

        # Nothing is certain enough to write at all.
        if not gate.committable and set(gate.pending) >= {"party"}:
            return self._decide("review", conf, flags, validation_dicts, gate,
                                "Party could not be resolved.")

        if gate.pending:
            # The useful case: write what is known, ask about the rest.
            return self._decide("commit_partial", conf, flags, validation_dicts, gate,
                                f"Confirm: {', '.join(gate.pending)}")

        if conf < floor:
            return self._decide("review", conf, flags, validation_dicts, gate,
                                "; ".join(flags))

        return self._decide("commit", conf, flags, validation_dicts, gate, "")

    def _decide(self, action, conf, flags, validations, gate, rationale) -> Decision:
        return Decision(
            output={
                "action": action,
                "flags": flags,
                "validations": validations,
                "pending_fields": gate.pending,
                "pending_reasons": gate.reasons,
            },
            confidence=conf,
            rationale=rationale,
            escalate=action != "commit",
        )
