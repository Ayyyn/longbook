"""Ledger analyst — nightly ageing, overdue crossings, and credit risk flags.

Produces the alerts that make the daily digest worth opening. Deterministic
maths; the model is used only to write the one-line explanation of *why* a
party is flagged (payment pattern deteriorating, cheque bounced, etc.).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agents.base import Agent, Decision
from app.services.ledger import ageing_buckets, overdue_crossings, payment_trend
from app.services.clock import business_today


class LedgerAnalyst(Agent):
    name = "ledger_analyst"
    prompt_version = "v1"

    def run(self, payload: dict[str, Any]) -> Decision:
        as_of: date = payload.get("as_of") or business_today()
        rules = (self.profile.rules if self.profile else {}) or {}
        overdue_days = rules.get("overdue_days", 45)

        buckets = ageing_buckets(self.db, self.tenant_id, as_of, overdue_days)
        crossings = overdue_crossings(self.db, self.tenant_id, as_of, overdue_days)
        risky = payment_trend(self.db, self.tenant_id, lookback_days=180)

        return Decision(
            output={
                "as_of": str(as_of),
                "ageing": buckets,
                "newly_overdue": crossings,
                "risk_flags": risky,
            },
            confidence=1.0,
            rationale=f"{len(crossings)} parties crossed {overdue_days} days.",
        )
