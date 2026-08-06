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
  "modules": {"lots": bool, "dispatch": bool, "job_work": bool,
              "catalog": bool, "credit_ledger": bool},
  "vocabulary": {"quantity_units": [...], "rate_basis": "...",
                 "quality_code_example": "...", "party_terms": [...]},
  "rules": {"overdue_days": int, "low_stock_threshold": number,
            "rate_deviation_pct": number},
  "confidence": 0.0-1.0,
  "reason": "..."
}

Base every inference on evidence in the sample. If the sample never shows dye
lots, set lots=false. If there are no credit terms or outstanding chases,
set credit_ledger=false. Do not apply defaults you cannot see evidence for.
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
