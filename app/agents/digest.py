"""Digest composer — the close-of-business summary.

Ranked by what the owner can still act on today. Delivered by email plus a
dashboard link; there is no auto-messaging of customers anywhere in this
system by design.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_json

SYSTEM = """Write a close-of-business summary for the owner of an Indian
textile business. Be concrete and terse — this is read on a phone in a market.

Return JSON only:
{"headline": "...", "sections": [{"title": "...", "items": ["..."]}],
 "action_items": ["..."], "confidence": 1.0}

Rules: lead with money (payments received, newly overdue), then orders, then
stock. Use INR with Indian digit grouping. Never invent a number that is not
in the input. If a section has nothing, omit it entirely.
"""


class DigestComposer(Agent):
    name = "digest_composer"
    prompt_version = "v1"

    def run(self, payload: dict[str, Any]) -> Decision:
        result, usage = generate_json(
            model=self.model,
            system=SYSTEM,
            user=str(payload["facts"]),
            locale=payload.get("locale", "en"),
        )
        return Decision(
            output=result, confidence=1.0, rationale="", meta={"usage": usage}
        )
