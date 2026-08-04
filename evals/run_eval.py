"""Extraction regression harness.

Build the golden set on day 2 from real messages, before tuning any prompt.
Run on every prompt change: under deadline pressure, a "fix" that silently
regresses order capture is the failure mode that loses the two weeks.

    python -m evals.run_eval --tenant <uuid>
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden_set.jsonl"


def field_match(expected: dict, got: dict) -> tuple[int, int]:
    hit = sum(1 for k, v in expected.items() if str(got.get(k, "")).lower() == str(v).lower())
    return hit, len(expected)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    args = ap.parse_args()

    cases = [json.loads(l) for l in GOLDEN.read_text().splitlines() if l.strip()]
    types_ok = 0
    f_hit = f_tot = 0
    confusion: Counter = Counter()

    # from app.agents import Extractor  # wire once DB session helper exists
    for case in cases:
        got = {"record_type": None, "fields": {}}   # TODO: call Extractor here
        if got["record_type"] == case["expect"]["record_type"]:
            types_ok += 1
        else:
            confusion[(case["expect"]["record_type"], got["record_type"])] += 1
        h, t = field_match(case["expect"].get("fields", {}), got["fields"])
        f_hit, f_tot = f_hit + h, f_tot + t

    n = len(cases) or 1
    print(f"type accuracy   : {types_ok}/{len(cases)} ({types_ok / n:.1%})")
    print(f"field accuracy  : {f_hit}/{f_tot or 1} ({f_hit / (f_tot or 1):.1%})")
    for (exp, got_t), c in confusion.most_common(10):
        print(f"  confused {exp} -> {got_t}: {c}")


if __name__ == "__main__":
    main()
