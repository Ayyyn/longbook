"""Answering questions about this business's own records.

Deliberately narrow. It is not an assistant: it has one corpus, this tenant's
records, and one rule, that every factual claim carries a citation to
something in that corpus. Anything it cannot cite it does not say.

That rule is enforced twice — once by telling the model, and once after the
fact by stripping the answer of claims whose citations do not resolve. Prompt
instructions are guidance; the check is what makes the citation reliable.

Isolation is not part of the prompt at all. The retrieval layer filters every
query by tenant, so there is nothing in the context to leak in the first
place.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_json
from app.services.retrieval import as_prompt, citation_map, gather

SYSTEM = """You answer questions about ONE textile business's own records.

You are given everything that business holds which might bear on the question,
each item tagged with a reference like [P1], [O2], [Q1] or [M3].

Rules, in order of importance:

1. EVERY factual claim must end with the reference it comes from, like
   "Ashok Textiles owes Rs 25,000 [P1]". A claim you cannot tag with a
   reference must not appear at all.
2. NEVER estimate, infer, extrapolate or fill a gap. If the records do not
   contain the answer, say plainly that you do not have it and name what is
   missing. "I do not have any dispatch records for that order" is a good
   answer. A guess is not.
3. Do not add up numbers the records do not already add up, unless the sum is
   of figures you cite individually.
4. Answer only about this business's trade — its parties, orders, payments,
   rates, dispatches and messages. For anything else, say it is outside what
   you can answer and leave it there. Do not give general advice, opinions,
   market commentary, or help with anything unrelated.
5. Be brief. A trader is reading this on a phone between customers. Two or
   three sentences, or a short list. No preamble.
6. Money in rupees, Indian digit grouping.

Return JSON:
{"answer": "...", "citations": ["P1","O2"], "answered": true|false,
 "missing": "what you would need in order to answer, if you could not"}

`answered` is false when the records do not support an answer."""


class Analyst(Agent):
    """Question in, cited answer out."""

    name = "analyst"
    prompt_version = "analyst-v1"

    def run(self, payload: dict[str, Any]) -> Decision:
        question = (payload.get("question") or "").strip()
        if not question:
            return Decision(
                output={"answer": "Ask me something about your business.",
                        "citations": [], "answered": False},
                confidence=1.0,
            )

        context = gather(self.db, self.tenant_id, question)
        refs = citation_map(context)

        # Nothing to answer from is answered here, not by the model. Sending an
        # empty context and hoping for a refusal is how you get an invented one.
        if not refs:
            return Decision(
                output={
                    "answer": (
                        "I do not have any records that answer that yet. "
                        "Add your chats or a party list and ask me again."
                    ),
                    "citations": [],
                    "answered": False,
                    "sources": [],
                },
                confidence=1.0,
                rationale="No records matched the question.",
            )

        history = payload.get("history") or []
        conversation = "\n".join(
            f"{turn['role']}: {turn['text']}" for turn in history[-6:]
        )

        user = (
            (f"Earlier in this conversation:\n{conversation}\n\n" if conversation else "")
            + f"Question: {question}\n\n"
            + "Records available to answer from:\n"
            + as_prompt(context)
        )

        result, usage = generate_json(
            model=self.model,
            system=SYSTEM,
            user=user,
        )

        answer = (result.get("answer") or "").strip()
        answered = bool(result.get("answered", True)) and bool(answer)

        # The second enforcement. A reference the model invented resolves to
        # nothing, and a sentence resting on it is a claim we cannot stand
        # behind — so it is removed rather than shown.
        cited = [c for c in re.findall(r"\[([A-Z]\d+)\]", answer) if c in refs]
        invented = [c for c in re.findall(r"\[([A-Z]\d+)\]", answer) if c not in refs]
        for bogus in invented:
            answer = answer.replace(f"[{bogus}]", "")

        if answered and not cited:
            answered = False
            answer = (
                "I could not point to a record that answers that, so I would "
                "rather not guess. Try naming the party, or ask about "
                "outstandings, orders or rates."
            )

        sources = []
        for ref in dict.fromkeys(cited):
            e = refs[ref]
            sources.append(
                {
                    "ref": ref,
                    "kind": e.kind,
                    "label": e.label,
                    "detail": e.detail,
                    "party_id": e.party_id,
                    "order_id": e.order_id,
                    "interaction_id": e.interaction_id,
                    "occurred_at": e.occurred_at,
                }
            )

        return Decision(
            output={
                "answer": answer.strip(),
                "citations": list(dict.fromkeys(cited)),
                "answered": answered,
                "missing": result.get("missing"),
                "sources": sources,
                "invented_citations": invented,
            },
            confidence=0.9 if answered else 0.4,
            rationale=f"{len(refs)} records considered, {len(cited)} cited.",
            meta={"usage": usage},
        )
