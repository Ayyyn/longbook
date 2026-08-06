"""Extraction regression harness.

Build the golden set on day 2 from real messages, before tuning any prompt.
Run on every prompt change: under deadline pressure, a "fix" that silently
regresses order capture is the failure mode that loses the two weeks.

    python -m evals.run_eval --tenant <uuid>
    python -m evals.run_eval --tenant <uuid> --save baseline
    python -m evals.run_eval --tenant <uuid> --compare baseline

Calls the live Extractor. `--compare` prints the per-case delta against a saved
run, which is the only honest way to tell a prompt improvement from a
coincidence.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).parent / "golden_set.jsonl"
RUNS = Path(__file__).parent / "runs"

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def _norm(value: Any) -> str:
    """Compare what the values mean, not how they were written.

    150, "150", 150.0 and " 150 " are the same answer; marking three of them
    wrong would make the score measure formatting rather than extraction.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    text = str(value).strip().lower()
    try:
        return f"{float(text.replace(',', '')):g}"
    except ValueError:
        return text


def field_match(expected: dict, got: dict) -> tuple[int, int]:
    hit = sum(1 for k, v in expected.items() if _norm(got.get(k)) == _norm(v))
    return hit, len(expected)


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_cases(tenant_id: uuid.UUID, cases: list[dict], limit: int | None = None) -> dict:
    """Run every case through the real Extractor, with the tenant's profile."""
    from sqlalchemy import select

    from app.agents import Extractor
    from app.db import tenant_session
    from app.models.party import Party
    from app.models.tenant import BusinessProfile

    results: list[dict] = []

    with tenant_session(tenant_id) as db:
        profile = db.execute(
            select(BusinessProfile).where(BusinessProfile.tenant_id == tenant_id)
        ).scalars().first()
        hints = list(
            db.execute(select(Party.name).where(Party.tenant_id == tenant_id).limit(40))
            .scalars()
            .all()
        )

        agent = Extractor(db, tenant_id, profile)
        selected = cases[:limit] if limit else cases

        for index, case in enumerate(selected, start=1):
            expected = case["expect"]
            started = time.perf_counter()
            try:
                decision = agent.execute(
                    {"body": case["message"], "party_hints": hints},
                    trace_id=uuid.uuid4(),
                )
                got_type = decision.output.get("record_type")
                got_fields = decision.output.get("fields", {}) or {}
                confidence = decision.confidence
                error = None
            except Exception as exc:  # noqa: BLE001 - a failed call is a failed case
                got_type, got_fields, confidence, error = None, {}, 0.0, str(exc)[:200]

            hit, total = field_match(expected.get("fields", {}), got_fields)
            results.append({
                "id": case.get("id", f"case-{index}"),
                "message": case["message"],
                "tags": case.get("tags", []),
                "expected_type": expected["record_type"],
                "got_type": got_type,
                "type_ok": got_type == expected["record_type"],
                "expected_fields": expected.get("fields", {}),
                "got_fields": got_fields,
                "field_hits": hit,
                "field_total": total,
                "confidence": confidence,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": error,
            })
            # Committed per case: a rate-limit stall halfway through should not
            # discard the cases that already ran.
            db.commit()
            print(
                f"  {index:>3}/{len(selected)} "
                f"{'ok ' if results[-1]['type_ok'] else 'MISS'} "
                f"{str(got_type):<8} {hit}/{total} fields  {case['message'][:52]!r}"
            )

    return summarise(results)


def summarise(results: list[dict]) -> dict:
    types_ok = sum(1 for r in results if r["type_ok"])
    hits = sum(r["field_hits"] for r in results)
    totals = sum(r["field_total"] for r in results)
    confidences = [r["confidence"] for r in results if r["confidence"] is not None]
    latencies = [r["latency_ms"] for r in results]

    confusion: Counter = Counter()
    per_type: dict[str, dict[str, int]] = {}
    per_field: dict[str, dict[str, int]] = {}

    for r in results:
        bucket = per_type.setdefault(r["expected_type"], {"n": 0, "ok": 0,
                                                          "f_hit": 0, "f_total": 0})
        bucket["n"] += 1
        bucket["ok"] += int(r["type_ok"])
        bucket["f_hit"] += r["field_hits"]
        bucket["f_total"] += r["field_total"]

        if not r["type_ok"]:
            confusion[(r["expected_type"], str(r["got_type"]))] += 1

        for key, want in r["expected_fields"].items():
            stat = per_field.setdefault(key, {"n": 0, "ok": 0})
            stat["n"] += 1
            stat["ok"] += int(_norm(r["got_fields"].get(key)) == _norm(want))

    return {
        "cases": len(results),
        "type_accuracy": round(types_ok / len(results), 4) if results else 0,
        "field_accuracy": round(hits / totals, 4) if totals else 0,
        "types_ok": types_ok,
        "field_hits": hits,
        "field_total": totals,
        "errors": sum(1 for r in results if r["error"]),
        "median_confidence": round(statistics.median(confidences), 3) if confidences else None,
        "median_latency_ms": int(statistics.median(latencies)) if latencies else None,
        "per_type": per_type,
        "per_field": per_field,
        "confusion": {f"{a} -> {b}": n for (a, b), n in confusion.most_common()},
        "results": results,
    }


def report(summary: dict) -> None:
    print()
    print(f"type accuracy   : {summary['types_ok']}/{summary['cases']} "
          f"({summary['type_accuracy']:.1%})")
    print(f"field accuracy  : {summary['field_hits']}/{summary['field_total']} "
          f"({summary['field_accuracy']:.1%})")
    print(f"median confidence: {summary['median_confidence']}")
    print(f"median latency   : {summary['median_latency_ms']} ms")
    if summary["errors"]:
        print(f"errors           : {summary['errors']}")

    print("\nby record type")
    for name, stat in sorted(summary["per_type"].items()):
        field_rate = stat["f_hit"] / stat["f_total"] if stat["f_total"] else 1.0
        print(f"  {name:<10} type {stat['ok']}/{stat['n']} "
              f"({stat['ok'] / stat['n']:.0%})   fields {stat['f_hit']}/{stat['f_total']} "
              f"({field_rate:.0%})")

    weak = sorted(
        ((k, v) for k, v in summary["per_field"].items() if v["n"] >= 2),
        key=lambda kv: kv[1]["ok"] / kv[1]["n"],
    )
    if weak:
        print("\nby field (worst first)")
        for name, stat in weak[:12]:
            print(f"  {name:<16} {stat['ok']}/{stat['n']} ({stat['ok'] / stat['n']:.0%})")

    if summary["confusion"]:
        print("\nconfusion")
        for label, count in summary["confusion"].items():
            print(f"  {label}: {count}")

    misses = [r for r in summary["results"] if not r["type_ok"] or r["field_hits"] < r["field_total"]]
    if misses:
        print(f"\nmisses ({len(misses)})")
        for r in misses:
            print(f"\n  [{r['id']}] {r['message']!r}")
            if not r["type_ok"]:
                print(f"      type: expected {r['expected_type']}, got {r['got_type']}")
            for key, want in r["expected_fields"].items():
                got = r["got_fields"].get(key)
                if _norm(got) != _norm(want):
                    print(f"      {key}: expected {want!r}, got {got!r}")
            if r["error"]:
                print(f"      error: {r['error']}")


def compare(current: dict, baseline: dict) -> None:
    """Per-case delta. A headline number can improve while cases regress."""
    print("\n" + "=" * 62)
    print("COMPARISON AGAINST BASELINE")
    print("=" * 62)

    t_delta = current["type_accuracy"] - baseline["type_accuracy"]
    f_delta = current["field_accuracy"] - baseline["field_accuracy"]
    print(f"type accuracy  {baseline['type_accuracy']:.1%} -> "
          f"{current['type_accuracy']:.1%}  ({t_delta:+.1%})")
    print(f"field accuracy {baseline['field_accuracy']:.1%} -> "
          f"{current['field_accuracy']:.1%}  ({f_delta:+.1%})")

    before = {r["id"]: r for r in baseline["results"]}
    fixed, broken = [], []
    for r in current["results"]:
        was = before.get(r["id"])
        if not was:
            continue
        now_score = (r["type_ok"], r["field_hits"])
        was_score = (was["type_ok"], was["field_hits"])
        if now_score > was_score:
            fixed.append(r)
        elif now_score < was_score:
            broken.append((r, was))

    print(f"\nfixed: {len(fixed)}   regressed: {len(broken)}")
    for r in fixed:
        print(f"  FIXED     [{r['id']}] {r['message'][:60]!r}")
    for r, was in broken:
        print(f"  REGRESSED [{r['id']}] {r['message'][:60]!r}")
        if was["type_ok"] and not r["type_ok"]:
            print(f"      type was {was['got_type']}, now {r['got_type']}")
        if r["field_hits"] < was["field_hits"]:
            print(f"      fields {was['field_hits']}/{was['field_total']} -> "
                  f"{r['field_hits']}/{r['field_total']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True, help="tenant whose profile shapes the prompt")
    ap.add_argument("--limit", type=int, help="run only the first N cases")
    ap.add_argument("--save", help="save this run under evals/runs/<name>.json")
    ap.add_argument("--compare", help="compare against a saved run")
    ap.add_argument("--tag", help="only cases carrying this tag")
    args = ap.parse_args()

    cases = load_cases()
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]
    print(f"{len(cases)} cases\n")

    summary = run_cases(uuid.UUID(args.tenant), cases, args.limit)
    report(summary)

    if args.save:
        RUNS.mkdir(parents=True, exist_ok=True)
        path = RUNS / f"{args.save}.json"
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nsaved {path}")

    if args.compare:
        path = RUNS / f"{args.compare}.json"
        if not path.exists():
            print(f"\nno baseline at {path}", file=sys.stderr)
            return 1
        compare(summary, json.loads(path.read_text(encoding="utf-8")))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
