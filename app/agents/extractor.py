"""Extractor — turns one interaction into a structured candidate record.

Reads the BusinessProfile so the prompt speaks the tenant's own vocabulary:
their units (meter/thaan/kg), their quality-code format, their party names.
This is what makes the same codebase work for a wholesaler and a retail shop.

Handles code-mixed Hindi/Gujarati/Marathi text natively via Gemini rather than
transcribe-then-parse, because surrounding context is what disambiguates
quantities and rates in trade shorthand ("150 mtr @ 62 nett").
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_json

SYSTEM = """You extract structured records from Indian textile trade messages.
The business uses these units: {units}
Quality/design codes usually look like: {code_hint}
Known party names include: {party_hint}

Classify the message as one of: order, payment, enquiry, dispatch, noise.
Return JSON only, no prose:
{{
  "record_type": "...",
  "fields": {{...}},
  "confidence": 0.0-1.0,
  "reason": "<why you are unsure, empty if confident>"
}}

Rules:
- Never invent a party or quality that is not in the message.
- Amounts in INR. Quantities keep the unit the message used.
- Trade shorthand: "nett" = no further discount, "thaan"/"than" = roll/piece.
- If the message is chit-chat, greetings, or a photo with no order intent,
  return record_type "noise" with confidence 1.0.
"""


class Extractor(Agent):
    name = "extractor"
    prompt_version = "v1"
    model = "gemini-2.5-flash"

    def run(self, payload: dict[str, Any]) -> Decision:
        vocab = (self.profile.vocabulary if self.profile else {}) or {}
        prompt = SYSTEM.format(
            units=", ".join(vocab.get("quantity_units", ["meter"])),
            code_hint=vocab.get("quality_code_example", "unknown"),
            party_hint=", ".join(payload.get("party_hints", [])[:40]) or "none yet",
        )

        result, usage = generate_json(
            model=self.model,
            system=prompt,
            user=payload["body"],
            media_uri=payload.get("media_uri"),
            media_kind=payload.get("media_kind"),
            examples=(self.profile.examples[:8] if self.profile else []),
        )

        conf = float(result.get("confidence", 0.0))
        return Decision(
            output={"record_type": result.get("record_type"), "fields": result.get("fields", {})},
            confidence=conf,
            rationale=result.get("reason", ""),
            escalate=conf < 0.75,
            meta={"usage": usage},
        )
