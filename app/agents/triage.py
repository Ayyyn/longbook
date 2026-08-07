"""Triage — decides auto-commit vs review queue.

Deliberately rule-first, model-second. Rules are auditable and free; the model
is only consulted when rules are inconclusive. This is the same
exception-triage shape as reconciliation break resolution.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision

AUTO_COMMIT_FLOOR = 0.85


class Triage(Agent):
    name = "triage"
    prompt_version = "v1"

    def run(self, payload: dict[str, Any]) -> Decision:
        conf = float(payload.get("confidence", 0))
        rules = (self.profile.rules if self.profile else {}) or {}
        flags: list[str] = []

        if payload.get("record_type") == "noise":
            return Decision(output={"action": "discard"}, confidence=1.0)

        # A defect or shortage claim always reaches a human. It leads to a
        # credit note or a replacement, and neither is a decision the system
        # should take on the owner's behalf however sure it is.
        if payload.get("record_type") == "complaint":
            return Decision(
                output={"action": "review", "flags": ["complaint"]},
                confidence=conf,
                rationale="Complaints are always reviewed.",
                escalate=True,
            )

        if conf < AUTO_COMMIT_FLOOR:
            flags.append(f"low_confidence({conf:.2f})")
        if payload.get("party_id") is None:
            flags.append("unresolved_party")

        # Numeric fields arrive already coerced by Extractor.normalise_fields;
        # unreadable ones are None and simply skip their rule.
        dev = payload.get("rate_deviation_pct")
        if dev is not None and abs(dev) > rules.get("rate_deviation_pct", 20):
            flags.append(f"rate_deviation({dev:.0f}%)")

        qty = payload.get("quantity")
        if qty is not None and qty <= 0:
            flags.append("implausible_quantity")

        if flags:
            return Decision(
                output={"action": "review", "flags": flags},
                confidence=conf,
                rationale="; ".join(flags),
                escalate=True,
            )
        return Decision(output={"action": "commit"}, confidence=conf)
