"""Writing the interview, instead of shipping one.

The nine fixed questions were a fabric-wholesaler questionnaire. A women's
clothing retailer was being asked whether they track dye lots; a bearing
distributor was asked what they sell by the meter. The questions themselves
told the owner the product was not built for them, before they had answered
any of them.

So the questions come from their data. Upload first, then two or three
universal questions, then questions written against what was actually in the
messages: "I can see lot numbers like BL-4471 in your chats — do those matter
when you sell?" is worth more than any fixed question, because it is already
half-answered and it proves something was read.

Cheap by design: one model call over a sample of messages, producing plain
questions with plain answer types. No dynamic schema, no invented tables. The
answers land in the same `Interview` shape the Configurator already reads.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_json

MAX_GENERATED = 8

SYSTEM = """You are setting up an operations tool for a business, by asking its
owner a few questions. You have a sample of their real WhatsApp messages.

Write the questions that would let you configure this business correctly, and
NOTHING else. Rules:

1. Ground every question in what you can actually see. Quote the evidence:
   "I can see codes like SR-1042 — is that how you identify what you sell?"
   A question you could have asked without reading the messages is a wasted
   question.
2. Ask about what you are UNSURE of. If the messages make something obvious,
   do not ask it — configure it and move on.
3. NEVER assume a trade. Do not ask about dye lots, meters, fabric, mills or
   any other industry's furniture unless that industry is visibly what this
   is. If the messages are about bearings, ask about bearings.
4. Plain language, answerable out loud, in a few seconds each. The owner is
   on a phone. No jargon, no compound questions.
5. At most {max_questions} questions. Fewer is better. Stop when more would
   not change how you configure the business.
6. Each question must map to one of these purposes, so the answer is usable:
   units, rate_basis, item_term, batch_tracking, credit_terms, dispatch,
   job_work, party_terms, other.

Answer types:
  "text"   — a short free answer
  "bool"   — yes or no
  "number" — a figure
  "choice" — one of options you provide (2-4, always include the likely one)

Return JSON:
{{"questions": [
  {{"key": "units", "purpose": "units", "type": "choice",
    "question": "...", "hint": "...", "options": ["...", "..."]}}
 ],
 "observations": ["what you noticed in the messages that shaped these"],
 "confidence": 0.0-1.0}}

`hint` is one short line under the question, and may be empty."""

# Asked before anything has been read, and true of any business anywhere.
# These are not a fallback — they always run first, and their answers are part
# of what the generator sees.
UNIVERSAL = [
    {
        "key": "what_kind",
        "purpose": "other",
        "type": "text",
        "question": "What kind of business is this?",
        "hint": "In your own words — a wholesaler, a distributor, a shop, a manufacturer.",
        "options": [],
    },
    {
        "key": "what_you_sell",
        "purpose": "other",
        "type": "text",
        "question": "What do you sell?",
        "hint": "Whatever you would tell a new customer who walked in.",
        "options": [],
    },
    {
        "key": "who_buys",
        "purpose": "party_terms",
        "type": "text",
        "question": "Who buys from you?",
        "hint": "Shops, mills, factories, the public — whoever they are.",
        "options": [],
    },
]

# Used when generation fails or there is nothing to read. Deliberately
# trade-neutral: bland questions beat a fabric questionnaire asked of a
# chemical distributor.
FALLBACK = [
    {
        "key": "units",
        "purpose": "units",
        "type": "text",
        "question": "What do you sell it by?",
        "hint": "Pieces, kilos, meters, boxes — the units you quote in.",
        "options": [],
    },
    {
        "key": "gives_credit",
        "purpose": "credit_terms",
        "type": "bool",
        "question": "Do your buyers pay after delivery?",
        "hint": "Rather than paying upfront.",
        "options": [],
    },
    {
        "key": "credit_days",
        "purpose": "credit_terms",
        "type": "number",
        "question": "How many days do they usually take to pay?",
        "hint": "Roughly. Leave blank if it varies.",
        "options": [],
    },
    {
        "key": "batch_tracking",
        "purpose": "batch_tracking",
        "type": "bool",
        "question": "Do you track batch or lot numbers?",
        "hint": "Say no if that never comes up in your messages.",
        "options": [],
    },
    {
        "key": "dispatch",
        "purpose": "dispatch",
        "type": "text",
        "question": "How do goods reach your buyers?",
        "hint": "Transport, courier, they collect — however it happens.",
        "options": [],
    },
]

ALLOWED_TYPES = {"text", "bool", "number", "choice"}
ALLOWED_PURPOSES = {
    "units", "rate_basis", "item_term", "batch_tracking", "credit_terms",
    "dispatch", "job_work", "party_terms", "other",
}


class Interviewer(Agent):
    """Reads the sample, writes the questions."""

    name = "interviewer"
    prompt_version = "interviewer-v1"

    def run(self, payload: dict[str, Any]) -> Decision:
        messages = [m for m in (payload.get("messages") or []) if m and m.strip()]
        answers = payload.get("answers") or {}

        # Nothing read means nothing to ground a question in, and a generated
        # question with no evidence is just a fixed question with extra steps.
        if not messages:
            return Decision(
                output={"questions": FALLBACK, "observations": [], "generated": False},
                confidence=0.3,
                rationale="No messages to read; using the neutral question set.",
            )

        said = "\n".join(f"- {k}: {v}" for k, v in answers.items() if v)
        sample = "\n".join(messages[:120])

        result, usage = generate_json(
            model=self.model,
            system=SYSTEM.format(max_questions=MAX_GENERATED),
            user=(
                (f"What the owner has already told us:\n{said}\n\n" if said else "")
                + f"A sample of their messages:\n{sample}"
            ),
        )

        questions = self._clean(result.get("questions"))
        if not questions:
            return Decision(
                output={"questions": FALLBACK, "observations": [], "generated": False},
                confidence=0.3,
                rationale="Generation returned nothing usable; using the neutral set.",
                meta={"usage": usage},
            )

        return Decision(
            output={
                "questions": questions,
                "observations": [
                    str(o) for o in (result.get("observations") or [])[:5]
                ],
                "generated": True,
            },
            confidence=float(result.get("confidence") or 0.7),
            rationale=f"{len(questions)} questions written from {len(messages)} messages.",
            meta={"usage": usage},
        )

    def _clean(self, raw: Any) -> list[dict]:
        """Drop anything malformed rather than showing it to an owner.

        A question with no text, an unknown answer type, or a `choice` with
        nothing to choose from is worse than one question fewer.
        """
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        seen: set[str] = set()
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("question") or "").strip()
            if not text or text.lower() in seen:
                continue
            kind = str(entry.get("type") or "text").strip().lower()
            if kind not in ALLOWED_TYPES:
                kind = "text"
            options = [str(o) for o in (entry.get("options") or []) if str(o).strip()]
            if kind == "choice" and len(options) < 2:
                kind = "text"
                options = []
            purpose = str(entry.get("purpose") or "other").strip().lower()
            if purpose not in ALLOWED_PURPOSES:
                purpose = "other"

            seen.add(text.lower())
            out.append(
                {
                    "key": str(entry.get("key") or f"q{len(out) + 1}").strip(),
                    "purpose": purpose,
                    "type": kind,
                    "question": text,
                    "hint": str(entry.get("hint") or "").strip(),
                    "options": options[:4],
                }
            )
            if len(out) >= MAX_GENERATED:
                break
        return out
