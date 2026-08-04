"""Draft composer — writes follow-up messages the OWNER sends.

Explicit product decision: this system never sends a message to a customer on
the owner's behalf. It drafts, the owner reviews, and the dashboard hands them
a wa.me link so the message goes from their own number in their own voice.

Reasons: a wrong autonomous message to a trade customer destroys trust
permanently, and it removes any dependency on WhatsApp Business API approval.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_json
from app.services.wa import wa_link

SYSTEM = """Draft a short payment-reminder or follow-up message from a textile
business owner to their customer.

Return JSON only: {"message": "...", "tone": "...", "confidence": 0.0-1.0}

Rules:
- Write in the language of the sample messages provided (often code-mixed
  Hindi/Gujarati in Latin script). Match the owner's own register.
- Respectful, brief, no legal threats, no guilt-tripping.
- State the specific invoice/amount/date. Never round or invent figures.
- Two to four lines maximum. No greetings longer than one line.
"""


class DraftComposer(Agent):
    name = "draft_composer"
    prompt_version = "v1"

    def run(self, payload: dict[str, Any]) -> Decision:
        result, usage = generate_json(
            model=self.model,
            system=SYSTEM,
            user=str(payload["context"]),
            examples=payload.get("owner_samples", [])[:5],
        )
        msg = result.get("message", "")
        return Decision(
            output={
                "message": msg,
                "wa_link": wa_link(payload["party_phone"], msg),
                "requires_owner_send": True,
            },
            confidence=float(result.get("confidence", 0.8)),
            meta={"usage": usage},
        )
