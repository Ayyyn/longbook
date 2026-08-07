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

You are given ONE CONVERSATION, as numbered lines. A single order is usually
built across several lines — a request, an availability reply, an amendment,
then a total. Read the whole conversation and report what it settled on, not
what each line says on its own. One conversation can contain several records:
an order and the payment for it, or two separate orders.

Return JSON only, no prose:
{{
  "records": [
    {{
      "record_type": "order|quote|payment|enquiry|dispatch|complaint|noise",
      "fields": {{...}},
      "confidence": 0.0-1.0,
      "reason": "<why you are unsure, empty if confident>",
      "source_lines": [1, 4, 7]
    }}
  ]
}}

"source_lines" lists the line numbers a record was drawn from. Always give it.
Return an empty "records" list if the conversation settled nothing.

FIELD NAMES ARE FIXED. Use exactly these keys and no others. Omit any you
cannot fill; never rename one, never invent a new one.

  order     party, quality, quantity, unit, rate, order_no, delivery_date,
            notes, lines
  payment   party, amount, mode, reference, received_on, cheque_date
            (mode is one of: cash, upi, neft, rtgs, cheque)
  dispatch  party, order_no, challan_no, transporter, lr_no, dispatched_on
  quote     party, quality, quantity, unit, rate, quoted_by, status, notes,
            counters
            (quoted_by is "us" or "them"; status is one of: offered,
             countered, accepted, rejected, lapsed)
  enquiry   party, quality, quantity, unit, rate, amount, notes
  complaint party, quality, quantity, unit, notes
  noise     (no fields)

When one message covers several things — whether ordering them or asking to be
quoted for them — put each in "lines", NOT "items", and give every line its own
quality, quantity, unit and rate:
  "lines": [{{"quality": "...", "quantity": 500, "unit": "m", "rate": 88}}]
A colour or shade with no separate design code goes in that line's "quality".
Use the unit names the business uses ({units}), not the abbreviation the
message happened to type.

A price haggled back and forth is a "quote", not an order and not an enquiry.
Report the WHOLE negotiation as ONE quote record: `rate` is the latest figure
on the table, `status` says where it ended up, and `counters` lists every
figure in order so the history is not lost:
  "counters": [{{"rate": 1600, "by": "them"}}, {{"rate": 1450, "by": "us"}},
               {{"rate": 1500, "by": "them"}}]
An order only exists once someone actually places one ("sending PO",
"received order", "confirmed"). Until then a agreed price is a quote with
status "accepted".

Rules:
- Never invent a party or quality that is not in the message.
- Amounts in INR. Quantities keep the unit the message used.
- Trade shorthand: "nett" = no further discount, "thaan"/"than" = roll/piece.
- Classify by what the message DOES, not by the words it contains:
    * A price offered, asked for, or countered is a "quote".
    * An order total or invoice value is not a payment. Only money that has
      actually moved is a payment.
    * Asking for something to be sent is an order, not a dispatch. Only a
      consignment that has actually left is a dispatch — but a plain statement
      that it has gone is one, even with no numbers in it ("Dispatch
      completed.", "Dispatched", "Bhej diya").
    * Money still owed is an enquiry, not a payment ("Payment pending
      1,09,824", "Balance 50000"). Nothing has moved yet.
    * A total worked out from an agreed rate and quantity is part of the
      quote or order it belongs to, not a separate record.
- "order" needs the buyer to commit to buying something: a quantity to send, a
  named product to send, an explicit yes ("done", "confirmed", "make it 250"),
  or a change to what was already ordered ("Wine should be 350m"). A message
  that commits to nothing is NOT an order, however much it is about one:
    "Expected Monday." -> noise      "One correction." -> noise
    "Keep for next order." -> noise  "Will clear by Saturday." -> noise
    "300 m per shade." -> enquiry    "94 final." -> enquiry
    * A report of damaged, short or defective goods is a "complaint" — a real
      event that leads to an adjustment, not chit-chat.
- Resolve the conversation before reporting it. If line 3 asks for 300m Olive
  and line 5 says "make it 250", the order is 250 — report the settled figure
  once, not both. If a later line corrects an earlier one, the correction wins.
- Report a running total the parties agreed ONCE, as the order's own fields;
  do not also emit the individual requests as separate records.
- Do not emit "noise" records. Chit-chat, greetings, acknowledgements and
  questions simply do not appear in "records" at all.
- Be confident when the conversation settled the matter, even if no single
  line did. Only go below 0.6 when the conversation itself leaves something
  genuinely open — a quantity nobody confirmed, a rate never agreed.
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


# The model reaches for a synonym often enough that the write boundary cannot
# assume the prompt was obeyed. Measured on a real export: it returned "items"
# for a three-colour order and every line was silently dropped, because
# commit.py looks for "lines". Renaming here keeps that failure impossible
# rather than merely unlikely.
FIELD_ALIASES = {
    "items": "lines",
    "line_items": "lines",
    "products": "lines",
    "party_name": "party",
    "customer": "party",
    "buyer": "party",
    "price": "rate",
    "rate_per_unit": "rate",
    "quality_or_design": "quality",
    "design": "quality",
    "quality_code": "quality",
    "qty": "quantity",
    "meters": "quantity",
    "payment_mode": "mode",
    "utr": "reference",
    "transaction_id": "reference",
    "lr_number": "lr_no",
    "lr": "lr_no",
    "challan": "challan_no",
    "order_number": "order_no",
    "delivery_by": "delivery_date",
    "promised_date": "delivery_date",
    "payment_date": "received_on",
    "date": "received_on",
}


def apply_aliases(fields: dict[str, Any]) -> dict[str, Any]:
    """Map known synonyms onto the contract, top level and per line."""
    if not isinstance(fields, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in fields.items():
        target = FIELD_ALIASES.get(key, key)
        if target == "lines" and isinstance(value, list):
            value = [apply_aliases(v) if isinstance(v, dict) else v for v in value]
        # A correctly-named key already present wins over a renamed one.
        if target not in out or out[target] in (None, "", [], {}):
            out[target] = value
    return out


class Extractor(Agent):
    name = "extractor"
    prompt_version = "v4"

    def run(self, payload: dict[str, Any]) -> Decision:
        """One conversation in, a list of records out.

        `payload["body"]` is the rendered window (numbered lines). The Decision
        carries `records`; its own confidence is the lowest of them, so the
        agent_run row still summarises how sure the pass was overall.
        """
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

        raw = result.get("records")
        if raw is None:
            # Tolerate the single-record shape: a model that ignores the
            # envelope should not cost the whole window.
            raw = [result] if result.get("record_type") else []

        records: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            record_type = item.get("record_type")
            if not record_type or record_type == "noise":
                continue

            conf = float(item.get("confidence", 0.0) or 0.0)
            fields, unreadable = normalise_fields(apply_aliases(item.get("fields", {})))
            rationale = item.get("reason", "") or ""

            if unreadable:
                # The record is otherwise fine; it is one number short, and that
                # is exactly the thing a human can fix in two seconds.
                conf = min(conf, UNREADABLE_FIELD_CEILING)
                note = f"could not read a number for: {', '.join(unreadable)}"
                rationale = f"{rationale}; {note}" if rationale else note

            records.append({
                "record_type": record_type,
                "fields": fields,
                "confidence": conf,
                "reason": rationale,
                "source_lines": [
                    n for n in (item.get("source_lines") or []) if isinstance(n, (int, float))
                ],
            })

        lowest = min((r["confidence"] for r in records), default=1.0)
        return Decision(
            output={"records": records},
            confidence=lowest,
            rationale=f"{len(records)} record(s) from {payload.get('message_count', 0)} messages",
            escalate=lowest < 0.75,
            meta={"usage": usage},
        )
