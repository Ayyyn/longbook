"""Resolver — links an extracted candidate to existing entities.

The hard part is party aliasing. "Ashok Tex", "ashok bhai", "A.T. Mumbai" are
one customer. Strategy is cheap-first:
  1. exact match on name or alias
  2. phone number match
  3. trigram similarity shortlist from Postgres
  4. only if still ambiguous, ask the model to choose among the shortlist

Ambiguity is escalated rather than guessed. A wrongly-attributed payment is
worse than a review-queue item.

Most trade messages name nobody at all — "150 mtr SR-1042 chahiye" is a
complete order in a chat where both sides already know who they are. For those
the sender *is* the party, which is why step 3 exists. It only runs when the
message named nobody: if the text does name a party, that party wins even when
somebody else forwarded the message.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision
from app.services.matching import phone_match, shortlist_parties, exact_alias_match


class Resolver(Agent):
    name = "resolver"
    prompt_version = "v2"

    def _is_us(self, name: str) -> bool:
        from app.models.tenant import Tenant
        from app.services.party_import import is_owner

        tenant = self.db.get(Tenant, self.tenant_id) if self.db else None
        return is_owner(name, None, tenant)

    def run(self, payload: dict[str, Any]) -> Decision:
        raw_name = (payload.get("fields", {}) or {}).get("party") or ""
        phone = payload.get("sender_phone")

        # A record's party is the counterparty, never the tenant. The model
        # names whoever the sentence is about, and on a dispatch that is the
        # business itself ("we sent it") — so a record would be attributed to
        # a party that deliberately does not exist. Fall through to the person
        # on the other side of the conversation instead.
        if raw_name and self._is_us(raw_name):
            raw_name = ""

        hit = exact_alias_match(self.db, self.tenant_id, raw_name)
        if hit:
            return Decision(output={"party_id": str(hit.id), "method": "alias"}, confidence=0.99)

        hit = phone_match(self.db, self.tenant_id, phone)
        if hit:
            return Decision(output={"party_id": str(hit.id), "method": "phone"}, confidence=0.95)

        if not raw_name.strip():
            hit = exact_alias_match(self.db, self.tenant_id, payload.get("sender_name") or "")
            if hit:
                return Decision(
                    output={"party_id": str(hit.id), "method": "sender"},
                    confidence=0.9,
                    rationale="Message named no party; attributed to the sender.",
                )

        candidates = shortlist_parties(self.db, self.tenant_id, raw_name, limit=5)
        if not candidates:
            return Decision(
                output={"party_id": None, "suggest_create": raw_name, "method": "none"},
                confidence=0.4,
                rationale="No existing party resembles this name.",
                escalate=True,
            )
        if len(candidates) == 1 and candidates[0].score > 0.85:
            return Decision(
                output={"party_id": str(candidates[0].id), "method": "trigram"},
                confidence=float(candidates[0].score),
            )

        return Decision(
            output={"candidates": [str(c.id) for c in candidates], "method": "ambiguous"},
            confidence=0.5,
            rationale=f"{len(candidates)} parties could match '{raw_name}'.",
            escalate=True,
        )
