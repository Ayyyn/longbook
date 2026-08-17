"""Answering questions about this business — from its records, and about them.

The rule is about evidence, not about topic. Every factual claim about this
business carries a citation to something in this tenant's records; anything it
cannot cite it does not say. Within that, it is allowed to think: what the
numbers mean, where the business is exposed, what to do about it. An earlier
version forbade the second thing along with the first, and answered "how could
I grow this business" with "that is outside what I can answer" — which is not
caution, it is a system refusing to use what it just read.

It can also search the web, for the things that are true of the world rather
than of this business: a prevailing rate, a GST rate, a festival date. Those
answers are grounded too, in pages rather than rows, and are reported as such.
The one thing it must never do is search for a fact about this business — the
records are the only authority on that.

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
4. Before saying an amount, date or figure is "not recorded", search the
   messages for it. Totals, invoice values and revised rates are very often
   agreed in chat and never make it onto a structured record — so a figure
   missing from `orders` is a reason to run `search_messages`, not a reason to
   report it as absent. Say a thing is not on record only after you have
   looked in the messages too.
5. Otherwise stop looking once you can answer. Do not call more lookups purely
   for completeness.

Writing the answer:

6. EVERY factual claim ends with the reference it came from, like
   "Mahalaxmi Dyeing owes Rs 12,500 [P1]". A claim you cannot tag must not
   appear. The references are in the `ref` field of each row.
7. NEVER estimate, infer or fill a gap, and NEVER derive a figure by
   arithmetic. Do not multiply a quantity by a rate to get a total. Do not add
   up numbers unless you cite each figure in the sum.

   If a total is stated in the records, use the stated total and cite it. If no
   total is stated, say the parts you can see — "1,390 metres at Rs 81.50 [M4]"
   — and do not compute the product. Quantities and rates often come from
   different messages, and multiplying them produces a number that looks
   authoritative, is not in the records, and is usually wrong once GST, credit
   notes or a revised rate are taken into account. Prefer an invoice figure
   over anything you could calculate.
8. Distinguish "the answer is nothing" from "I have no records". If the
   lookups ran and came back empty, say the nil result as a fact — "nobody has
   an outstanding balance", "every order has been dispatched". Only say you
   lack records when nothing has been added to the business at all. An owner
   reading "I have no balance records" concludes the app is broken; reading
   "nobody owes you anything" concludes their books are clear. Those are
   opposite meanings and only one is true.
9. You are allowed to think, not only to fetch. If the owner asks what their
   records mean, where they are exposed, which customer is worth chasing, or
   how they might grow — answer properly. Ground it in what you looked up, say
   which records led you there, and be concrete: "Mahavir is 40% of your
   receivables [P1, P2] — that is your biggest single risk" is useful; "consider
   diversifying your customer base" is a horoscope.

   The line that matters is not topic, it is evidence. A fact about this
   business must come from a lookup and carry its reference. A judgement built
   on those facts is yours to make, and should be recognisable as judgement —
   "that suggests", "you may want to" — rather than dressed up as a record.

   Decline only what you genuinely should: legal, tax and accounting rulings
   ("is this GST treatment correct"), anything about a named person's private
   affairs, and anything you would have to invent to answer. Say plainly what
   you cannot do and answer the part you can.
10. You can search the web, and it happens by itself when you need it — there
   is no lookup to call. Use it for things that are true of the world rather
   than of this business: a prevailing market rate, a GST rate, an HSN code, a
   festival date affecting demand, what a term means. Say when a figure came
   from the web rather than their books, because the owner must never mistake
   one for the other. Never search for a fact about this business — their
   records are the only authority on that, and the web has nothing to say
   about who owes them money.
11. Be brief. This is read on a phone between customers. Two or three
   sentences, or a short list. No preamble, no restating the question.
12. Money in rupees, Indian digit grouping.
13. When you list more than two things, use a markdown list — one "- " item
    per line, each on its own line. Do not run a list into a paragraph.
    Bold a figure with **1,42,000** when it is the point of the answer.
14. You CAN draw charts. When a comparison across parties, items or dates is
    the point of the answer — or whenever one is asked for — emit a fenced
    block tagged `chart`, one row per line:

    ```chart
    bar: Outstanding by party
    Mahalaxmi Dyeing = 12500
    Arihant Garments = 8000
    ```

    First line is the type and title: `bar:` to compare amounts, `share:` for
    percentages of a whole, `line:` for a figure over time. Every other line is
    `label = number`. Nothing else, no JSON, no units inside the numbers.
    At most 8 rows, largest first. Only real values from the lookups — if you
    have no numbers, write no chart. Put the figures in the surrounding text
    with their citations too: the chart is the picture, the sentence is the
    evidence.

Write the answer as markdown, not JSON."""


class Analyst(Agent):
    """Question in, cited answer out — with the lookups chosen by the model."""

    name = "analyst"
    prompt_version = "analyst-v4-advice-web"

    @property
    def model(self) -> str:
        from app.config import settings

        return self.model_override or settings().model_chat

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
            # The world outside their books: a prevailing rate, a GST rate, a
            # festival date. Never a fact about this business — the records are
            # the only authority on that, and the prompt says so.
            web_search=True,
        )
        answer = (answer or "").strip()

        # Pages a server-side search leant on. Kept apart from `refs` on
        # purpose: a record citation is checked and stripped if invented,
        # whereas these are reported by the API rather than echoed by the
        # model, so there is nothing to verify and nothing to strip.
        # Deduped by site, not by URL: a search routinely returns four pages
        # from indiamart, and four identical-looking lines under an answer
        # reads as padding rather than as evidence.
        web_sources: list[dict[str, Any]] = []
        seen_sites: set[str] = set()
        for step in trace:
            for src in step.get("sources") or []:
                site = (src.get("title") or src.get("url") or "").lower()
                if site and site not in seen_sites:
                    seen_sites.add(site)
                    web_sources.append(src)

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
        # A web-grounded answer has evidence, just not in the books — "GST on
        # cotton fabric is 5%" is sourced, cited to a page, and correct. The
        # figure check exists to catch numbers with nothing behind them, so
        # grounding satisfies it exactly as a record reference does. Without
        # this, every question the web answered would be clobbered into "I
        # could not point to a record", which is both false and a worse answer
        # than the one it replaces.
        claims_a_figure = bool(re.search(r"\d", answer))
        if answered and not cited and not web_sources and claims_a_figure:
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
                # Only what the label does not already say, and only what is
                # worth reading. Dumping every field produced lines like
                # "Arihant Garments — name: Arihant Garments, kind: customer,
                # credit_days: 0", which repeats the heading and then reports
                # a zero nobody asked about.
                "detail": _detail(row),
                "party_id": row.get("_id") if row.get("tool") in
                            {"find_parties", "outstanding"} else None,
                "order_id": row.get("_id") if row.get("tool") == "orders" else None,
                "interaction_id": row.get("_id") if row.get("tool") == "search_messages"
                                  else None,
                "occurred_at": row.get("when") or row.get("date") or row.get("received_on"),
            })

        # Web pages go in the same list, marked as web. The owner needs to be
        # able to tell at a glance which part of an answer came from their
        # books and which came from the internet — that distinction is the
        # whole reason a business would trust the first kind.
        for src in web_sources:
            sources.append({
                "ref": None,
                "kind": "web",
                "label": src.get("title") or src.get("url"),
                "detail": src.get("url"),
                "url": src.get("url"),
                "party_id": None, "order_id": None,
                "interaction_id": None, "occurred_at": None,
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


# Fields that only matter when they say something. A zero credit period or a
# blank city is noise in a citation, not evidence.
_SKIP_IF_FALSY = {"credit_days", "outstanding", "days_overdue", "quantity", "rate"}
_LABELLED = {"name", "party", "sender"}
# Never shown in a citation. `lines` is the raw order detail the model reads to
# answer from; rendering it produced a Python dict repr in the UI, which is a
# debugging artefact rather than evidence. `summary` says the same thing.
_NOT_EVIDENCE = {"lines"}


def _detail(row: dict) -> str:
    """A readable one-liner for a cited record."""
    parts = []
    for key, value in row.items():
        if key in {"ref", "tool", "_id"} or key in _LABELLED or key in _NOT_EVIDENCE:
            continue
        if value in (None, "", []):
            continue
        if key in _SKIP_IF_FALSY and not value:
            continue
        pretty = key.replace("_", " ")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        parts.append(f"{pretty} {value}")
    return ", ".join(parts)[:300]


def db_has_records(db, tenant_id, Party, Interaction, func, select) -> bool:
    """Does this tenant hold anything at all worth answering from?"""
    for model in (Party, Interaction):
        count = db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        ).scalar_one()
        if count:
            return True
    return False
