"""Working out how somebody's spreadsheet is laid out.

The deterministic reader in `party_import` matches column headings against a
list of spellings. That is fast, free and correct for a file shaped the way we
guessed — and useless for one that is not. Real books are not shaped the way we
guessed: the customer list is the third sheet, the header is on row 7 under a
company name and a date range, the name column says "Ledger A/c" or
"Particulars" or nothing at all, and there are four other sheets of invoices
and stock beside it.

So the model is asked one question: **where is the party list, and which
column is which?** It answers with a sheet name, a header row and a set of
column indexes.

It is deliberately NOT asked for the parties themselves. Handing back rows
means a model transcribing names, phone numbers and rupee amounts — which
truncates on a long sheet, and invents a digit often enough to matter on a
number somebody will chase a customer for. Mapping is judgement, which is what
a model is good at; reading a cell is not, and stays in code.

One call per upload, over a small sample of each sheet. The values never leave
openpyxl.
"""

from __future__ import annotations

from typing import Any

from app.agents.base import Agent, Decision
from app.llm import generate_json

# How much of each sheet the model is shown. Enough to see a header and infer
# what the rows are; not so much that a 5,000-row ledger is sent to be read.
SAMPLE_ROWS = 12
SAMPLE_COLS = 20
MAX_SHEETS = 12

FIELDS = ("name", "phone", "city", "gstin", "credit_days", "outstanding", "kind")

SYSTEM = """You are reading a small business's spreadsheet to find its list of
customers or suppliers — the parties it trades with.

You are given a sample of every sheet in the workbook, as rows of cells with
their row and column numbers.

Find the ONE sheet that lists parties, and say which column holds what.

Rules:

1. A party list has one row per business or person, with something that reads
   like a name. Sheets of invoices, stock, payments or summaries are NOT party
   lists, even when they mention party names — prefer the sheet where each
   name appears once and the row is *about* that party.
2. header_row is the 0-based row index of the headings. If the sheet has no
   heading row at all and the data starts immediately, use -1 and map columns
   by what the values look like.
3. Column numbers are 0-based, counting from the first column shown.
4. Map only what is actually there. Omit a field entirely rather than guessing
   a column for it. A wrong phone column is worse than no phone column.
5. "outstanding" is money the party owes, however it is labelled — balance,
   closing balance, due, baki. If both opening and closing exist, choose
   closing. Ignore debit/credit column pairs; if the amount is split across
   two columns, omit outstanding rather than picking one.
6. "kind" is a column saying customer or supplier. Omit it if absent.
7. If no sheet is a party list, return found=false. Say so plainly rather than
   forcing a mapping onto an invoice sheet.

Return JSON only:
{
  "found": true,
  "sheet": "<exact sheet name>",
  "header_row": 6,
  "columns": {"name": 1, "phone": 3, "outstanding": 7},
  "rationale": "<one short sentence>",
  "confidence": 0.0-1.0
}
"""


class SheetMapper(Agent):
    """Locates the party list in a workbook and maps its columns."""

    name = "sheet_mapper"
    prompt_version = "v1"

    def run(self, payload: dict[str, Any]) -> Decision:
        sheets = payload.get("sheets") or []
        if not sheets:
            return Decision(
                output={"found": False},
                confidence=0.0,
                rationale="Workbook had no readable sheets.",
            )

        lines: list[str] = []
        for sheet in sheets[:MAX_SHEETS]:
            lines.append(f'=== sheet: "{sheet["name"]}" ===')
            for row_index, row in enumerate(sheet["rows"]):
                cells = " | ".join(
                    f"[{col}] {value}" for col, value in enumerate(row) if value not in (None, "")
                )
                if cells:
                    lines.append(f"row {row_index}: {cells}")

        output, usage = generate_json(
            model=self.model,
            system=SYSTEM,
            user="\n".join(lines),
        )

        found = bool(output.get("found"))
        columns = {
            key: int(value)
            for key, value in (output.get("columns") or {}).items()
            if key in FIELDS and isinstance(value, (int, float)) and int(value) >= 0
        }
        # A mapping without a name column is not a mapping. Everything else is
        # optional; this is the one that decides whether a row is a party.
        if "name" not in columns:
            found = False

        return Decision(
            output={
                "found": found,
                "sheet": output.get("sheet"),
                "header_row": int(output.get("header_row", -1) or -1),
                "columns": columns,
            },
            confidence=float(output.get("confidence") or (0.6 if found else 0.0)),
            rationale=str(output.get("rationale") or "")[:400],
            meta={"usage": usage},
        )
