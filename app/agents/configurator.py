"""Configurator — the differentiator.

Runs once per tenant at onboarding. Takes a short structured interview plus a
sample of the business's own WhatsApp history and documents, and emits a
BusinessProfile: segments, active modules, vocabulary, and alert rules.

This is the agent that makes one codebase fit a fabric wholesaler and a
garment retailer without a fork — and the reason the product generalises to
jewellery or machinery later without a rewrite.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision
from app.config import settings
from app.llm import generate_json

SYSTEM = """You are configuring an operations system for an Indian business.

You will be given: answers to an onboarding interview, and a sample of real
messages from the business's WhatsApp history.

Infer how this business actually works and return JSON only:
{
  "segments": ["wholesaler"|"retail"],
  "modules": {"batches": bool, "dispatch": bool, "job_work": bool,
              "catalog": bool, "credit_ledger": bool},
  "vocabulary": {"quantity_units": [...], "rate_basis": "...",
                 "quality_code_example": "...", "party_terms": [...]},
  "rules": {"overdue_days": int, "low_stock_threshold": number,
            "rate_deviation_pct": number},
  "rules_evidence": {"overdue_days": <how many separate messages support this>,
                     "low_stock_threshold": int, "rate_deviation_pct": int},
  "confidence": 0.0-1.0,
  "reason": "..."
}

Base every inference on evidence in the sample. If the sample never shows dye
lots, set lots=false. If there are no credit terms or outstanding chases,
set credit_ledger=false. Do not apply defaults you cannot see evidence for.

Who the business sells to changes what most of this should be, and the owner
is asked directly — take their answer seriously rather than re-deriving it:

- **B2B** (sells to other businesses): the counterparty is a named account
  that comes back. credit_ledger is almost certainly true, party_terms
  matter, and overdue_days is a real number they will act on.
- **B2C** (sells to the public): most buyers are walk-ins who will never be a
  row worth keeping. credit_ledger should be false unless the sample actually
  shows the owner chasing individuals for money, and an outstanding report
  about walk-ins is noise that will make them distrust the whole product. Set
  segments to ["retail"].
- **Both**: configure for the B2B side, which is where the money is tracked,
  but do not infer credit terms from counter sales.

For every threshold in "rules", say in "rules_evidence" how many SEPARATE
messages support it. Count honestly: one negotiation is one observation, not
evidence of a general rule. A threshold supported by fewer than 3 observations
will be ignored in favour of the industry default, so an inflated count only
produces a worse configuration.
"""


class Configurator(Agent):
    name = "configurator"
    prompt_version = "v1"
    # Runs once per tenant, so quality over cost — but a free-tier key has no
    # pro quota at all, and onboarding must not die on that. See run() below.
    model_override = None

    @property
    def model(self) -> str:
        return settings().model_deep

    def run(self, payload: dict[str, Any]) -> Decision:
        user = (
            f"INTERVIEW ANSWERS:\n{payload['interview']}\n\n"
            f"MESSAGE SAMPLE ({len(payload['sample'])} messages):\n"
            + "\n".join(payload["sample"][:300])
        )
        try:
            result, usage = generate_json(model=self.model, system=SYSTEM, user=user)
        except Exception:  # noqa: BLE001 - fall back a tier rather than fail onboarding
            result, usage = generate_json(
                model=settings().model_deep_fallback, system=SYSTEM, user=user
            )
        conf = float(result.get("confidence", 0.0))
        return Decision(
            output=result,
            confidence=conf,
            rationale=result.get("reason", ""),
            escalate=conf < 0.7,
            meta={"usage": usage},
        )
