"""Extractor — turns one interaction into a structured candidate record.

Reads the BusinessProfile so the prompt speaks the tenant's own vocabulary:
their units (meter/thaan/kg), their quality-code format, their party names.
This is what makes the same codebase work for a wholesaler and a retail shop.

Handles code-mixed Hindi/Gujarati/Marathi text natively via Gemini rather than
transcribe-then-parse, because surrounding context is what disambiguates
quantities and rates in trade shorthand ("150 mtr @ 62 nett").
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_json

# Fields every downstream consumer treats as a number — triage thresholds,
# ageing buckets, quantity rollups. The model returns whatever the message
# said ("150 mtr", "62 nett", "1,25,000"), so the agent normalises once here
# rather than every caller guarding against a string.
NUMERIC_FIELDS = frozenset(
    {"quantity", "rate", "amount", "balance", "discount_pct", "rate_deviation_pct"}
)

# Floats, not Decimal: the Decision goes into agent_run.decision (JSONB) and
# Decimal is not JSON-serialisable. Exactness is re-established at the write
# boundary, where app/services/commit.py converts to Decimal for the Numeric
# columns the owner will check against Tally.
_NUMERIC_RE = re.compile(r"-?\d+(?:\.\d+)?")

# A number we could not read must not auto-commit. This sits below the 0.85
# floor so the record lands in the review queue with the field left blank.
UNREADABLE_FIELD_CEILING = 0.6

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


def coerce_number(value: Any) -> float | None:
    """Read the number out of whatever the message wrote.

    "150" -> 150.0, "1,25,000" -> 125000.0, "62 nett" -> 62.0, "kuch" -> None.
    Indian digit grouping is stripped before parsing, so the lakh separator
    never truncates an amount.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).replace(",", "").strip()
    match = _NUMERIC_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def normalise_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Coerce known numeric fields in place, top level and per line.

    Returns the normalised fields and the names of any that were present but
    unreadable — those become None, and the caller lowers its confidence.
    """
    if not isinstance(fields, dict):
        return {}, []

    unreadable: list[str] = []

    def normalise(scope: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in scope.items():
            if key == "lines" and isinstance(value, list):
                out[key] = [
                    normalise(line, f"lines[{i}].") if isinstance(line, dict) else line
                    for i, line in enumerate(value)
                ]
            elif key in NUMERIC_FIELDS:
                number = coerce_number(value)
                if number is None and value not in (None, ""):
                    unreadable.append(f"{prefix}{key}")
                out[key] = number
            else:
                out[key] = value
        return out

    return normalise(fields), unreadable


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
        fields, unreadable = normalise_fields(result.get("fields", {}))
        rationale = result.get("reason", "")

        if unreadable:
            # The record is otherwise fine; it is one number short, and that is
            # exactly the thing a human can fix in two seconds from the queue.
            conf = min(conf, UNREADABLE_FIELD_CEILING)
            note = f"could not read a number for: {', '.join(unreadable)}"
            rationale = f"{rationale}; {note}" if rationale else note

        return Decision(
            output={"record_type": result.get("record_type"), "fields": fields},
            confidence=conf,
            rationale=rationale,
            escalate=conf < 0.75,
            meta={"usage": usage},
        )
