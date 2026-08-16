"""Answering questions about this business's own records.

Deliberately narrow. It is not a general assistant: it has one corpus, this
tenant's records, and one rule, that every factual claim carries a citation to
something in that corpus. Anything it cannot cite it does not say.

What changed, and why
---------------------
The first version pre-computed a context by keyword-matching the question:

    asks_money = any(w in lowered for w in ("owe", "outstanding", "due", ...))

so "who owes me money" worked and "kya chal raha hai", "anything stuck with
Mahalaxmi" or "is Sharma behind again" returned nothing at all — and the agent
then truthfully reported that it had no records, about a business whose
records were sitting right there. The failure was a regex, but it read to the
owner as the product not knowing their own data, which is worse than a wrong
answer.

Now the model is given lookups and decides for itself what to fetch, in as
many steps as it needs. Understanding the question is the model's job, which
it is good at; a word list was never going to do it.

Isolation is unchanged and is not part of the prompt. `build_tools` closes over
the session and tenant id, so the model chooses which question to ask and can
never choose whose data to ask it of.

Citations survive the change. Every row a tool returns is re-labelled with a
short token, and the answer is stripped of any reference that does not resolve
to one — the same two-stage enforcement as before: tell the model, then check.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_with_tools
from app.services.ask_tools import build_tools

# Short tokens per record kind. UUIDs are unusable as citations: a model asked
# to echo "P3f2c1a8-..." gets a character wrong often enough to strip real
# citations as invented ones.
KIND_LETTERS = {
    "find_parties": "P", "outstanding": "P", "overdue": "I",
    "orders": "O", "payments": "Y", "rate_history": "L",
    "search_messages": "M",
}

SYSTEM = """You answer questions about ONE small business's own records.

You have lookups. Use them. Do not answer from memory or assumption — every
number you give must have come back from a lookup in this conversation.

How to work:

1. Read what the owner is actually asking, however they phrase it. They may
   write in English, Hindi or Gujarati, or mix them, and they will not use
   your vocabulary. "kaun kitna dena hai", "anything stuck", "is Sharma behind
   again" are all ordinary questions about outstandings and orders.
2. Choose lookups accordingly. Call several if that is what it takes. If a
   name is unfamiliar, call find_parties first to see who exists rather than
   guessing at a spelling.
3. If a lookup comes back empty, that is an answer, not a failure — but check
   an alternative before concluding. Empty `orders` for a party you found is
   "no orders on record for them", not "I have no records".
4. Stop looking once you can answer. Do not call more lookups for completeness.

Writing the answer:

5. EVERY factual claim ends with the reference it came from, like
   "Mahalaxmi Dyeing owes Rs 12,500 [P1]". A claim you cannot tag must not
   appear. The references are in the `ref` field of each row.
6. NEVER estimate, infer or fill a gap. Do not add up numbers unless you cite
   each figure in the sum.
7. Distinguish "the answer is nothing" from "I have no records". If the
   lookups ran and came back empty, say the nil result as a fact — "nobody has
   an outstanding balance", "every order has been dispatched". Only say you
   lack records when nothing has been added to the business at all. An owner
   reading "I have no balance records" concludes the app is broken; reading
   "nobody owes you anything" concludes their books are clear. Those are
   opposite meanings and only one is true.
8. Answer only about this business's trade. For anything else, say it is
   outside what you can answer and stop. No general advice or opinions.
9. Be brief. This is read on a phone between customers. Two or three
   sentences, or a short list. No preamble, no restating the question.
10. Money in rupees, Indian digit grouping.

Write the answer as plain text, not JSON."""


class Analyst(Agent):
    """Question in, cited answer out — with the lookups chosen by the model."""

    name = "analyst"
    prompt_version = "analyst-v2-tools"

    def run(self, payload: dict[str, Any]) -> Decision:
        question = (payload.get("question") or "").strip()
        if not question:
            return Decision(
                output={"answer": "Ask me something about your business.",
                        "citations": [], "answered": False, "sources": []},
                confidence=1.0,
            )

        raw_tools = build_tools(self.db, self.tenant_id)

        # Re-label rows with short tokens as they come back, and remember what
        # each token was, so a citation can be resolved afterwards.
        refs: dict[str, dict[str, Any]] = {}
        counters: dict[str, int] = {}

        def wrap(tool_name: str, fn):
            letter = KIND_LETTERS.get(tool_name, "R")

            def run(**kwargs):
                result = fn(**kwargs)
                for row in result.get("rows", []) if isinstance(result, dict) else []:
                    counters[letter] = counters.get(letter, 0) + 1
                    token = f"{letter}{counters[letter]}"
                    # The tool's own ref carries the record's UUID. It is
                    # replaced with a short token the model can echo, but the
                    # id is kept so the answer can still link to the record.
                    original = str(row.get("ref") or "")
                    row["ref"] = token
                    refs[token] = {"tool": tool_name, "_id": original[1:], **row}
                return result

            return run

        tools = {
            name: {"declaration": spec["declaration"], "run": wrap(name, spec["run"])}
            for name, spec in raw_tools.items()
        }

        history = [
            {"role": turn.get("role", "user"),
             "content": turn.get("text") or turn.get("content") or ""}
            for turn in (payload.get("history") or [])[-8:]
        ]

        answer, trace, usage = generate_with_tools(
            model=self.model,
            system=SYSTEM,
            user=question,
            tools=tools,
            history=history,
        )
        answer = (answer or "").strip()

        # Second enforcement, unchanged in spirit: a reference the model made
        # up resolves to nothing, and a sentence resting on it is a claim we
        # cannot stand behind, so it is removed rather than shown.
        # Models group references — "[O1, U1]" and "[O1][O2]" both occur — and a
        # regex that only matches a single token per bracket silently lets an
        # invented one through in the grouped form, which is exactly the case
        # the check exists to catch.
        found: list[str] = []
        for group in re.findall(r"\[([^\]]+)\]", answer):
            found.extend(re.findall(r"[A-Z]\d+", group))
        cited = [c for c in found if c in refs]
        invented = [c for c in found if c not in refs]

        def _clean_group(match: re.Match) -> str:
            keep = [t for t in re.findall(r"[A-Z]\d+", match.group(1)) if t in refs]
            return f"[{', '.join(keep)}]" if keep else ""

        answer = re.sub(r"\[([^\]]+)\]", _clean_group, answer)
        # Removing a citation leaves " ." and doubled spaces behind.
        answer = re.sub(r"\s+([.,;:])", r"\1", answer)
        answer = re.sub(r"[ \t]{2,}", " ", answer).strip()

        looked = sum(1 for _ in trace)
        rows_seen = len(refs)
        answered = bool(answer)

        # "Nobody owes you anything" and "this business has nothing in it yet"
        # read almost the same and mean opposite things. The first is a real
        # answer to a real question; the second means setup has not delivered
        # anything to answer from, and the screen should say so rather than
        # imply the books are clear. One cheap existence check separates them.
        if rows_seen == 0:
            from sqlalchemy import func, select

            from app.models.ingestion import Interaction
            from app.models.party import Party

            has_any = db_has_records(self.db, self.tenant_id, Party, Interaction,
                                     func, select)
            if not has_any:
                answered = False

        # No citation is only a failure when the answer asserts something that
        # needs one. "Nobody owes you anything" is a correct, complete answer
        # to a lookup that came back empty, and clobbering it with a shrug —
        # which the first version did — turns a clean answer into a defect.
        # A figure, though, must always be traceable — whether or not any
        # lookup returned rows. An invented number with no rows behind it is
        # the most dangerous output this thing can produce.
        claims_a_figure = bool(re.search(r"\d", answer))
        if answered and not cited and claims_a_figure:
            answered = False
            answer = (
                "I could not point to a record that answers that, so I would "
                "rather not guess. Try naming the party, or ask about "
                "outstandings, orders or rates."
            )
        if not answer:
            answered = False
            answer = (
                "I could not work that out from your records. Try naming the "
                "party, or ask about outstandings, orders or rates."
            )

        sources = []
        for ref in dict.fromkeys(cited):
            row = refs[ref]
            sources.append({
                "ref": ref,
                "kind": row.get("tool"),
                "label": row.get("party") or row.get("name") or row.get("sender") or "record",
                "detail": ", ".join(
                    f"{k}: {v}" for k, v in row.items()
                    if k not in {"ref", "tool", "_id"} and v not in (None, "", [])
                )[:300],
                "party_id": row.get("_id") if row.get("tool") in
                            {"find_parties", "outstanding"} else None,
                "order_id": row.get("_id") if row.get("tool") == "orders" else None,
                "interaction_id": row.get("_id") if row.get("tool") == "search_messages"
                                  else None,
                "occurred_at": row.get("when") or row.get("date") or row.get("received_on"),
            })

        return Decision(
            output={
                "answer": answer.strip(),
                "citations": list(dict.fromkeys(cited)),
                "answered": answered,
                "missing": None if answered else "a matching record",
                "sources": sources,
                "invented_citations": invented,
                "lookups": trace,
            },
            confidence=0.9 if answered else 0.4,
            rationale=f"{looked} lookups, {rows_seen} rows seen, {len(cited)} cited.",
            meta={"usage": usage, "lookups": trace},
        )


def db_has_records(db, tenant_id, Party, Interaction, func, select) -> bool:
    """Does this tenant hold anything at all worth answering from?"""
    for model in (Party, Interaction):
        count = db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        ).scalar_one()
        if count:
            return True
    return False
