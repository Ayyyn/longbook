"""Window-level extraction harness.

The unit of extraction is a conversation, and a conversation yields a *set* of
records. So a single "was it right" is not enough: a pass can miss a record
(recall) or invent one (precision), and those are different failures with
different costs. Inventing an order is worse than missing an enquiry.

    python -m evals.run_window_eval --tenant <uuid> --save v5-windows
    python -m evals.run_window_eval --tenant <uuid> --compare v5-windows
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

from evals.run_eval import _lines_match, _norm

GOLDEN = Path(__file__).parent / "golden_windows.jsonl"
RUNS = Path(__file__).parent / "runs"

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def render(messages: list[list[str]]) -> str:
    """Same shape windowing.Segment.render() produces, so the eval and
    production hand the model an identically formatted conversation."""
    lines = []
    for index, (sender, body) in enumerate(messages, start=1):
        lines.append(f"[{index}] 12/06 09:{index:02d} {sender}: {(body or '').replace(chr(10), ' / ')}")
    return "\n".join(lines)


def field_score(expected: dict, got: dict) -> tuple[int, int]:
    hit = 0
    for key, want in expected.items():
        if key == "lines" and isinstance(want, list):
            hit += int(_lines_match(want, got.get("lines")))
        elif _norm(got.get(key)) == _norm(want):
            hit += 1
    return hit, len(expected)


def pair_records(expected: list[dict], got: list[dict]) -> tuple[list, list, list]:
    """Greedily match produced records to expected ones by type, best fields first.

    Returns (matched pairs, unmatched expected = misses, unmatched got =
    spurious). Matching on type first is deliberate: a payment produced where
    an order was expected is not a partially-correct order, it is one of each
    kind of error.
    """
    remaining = list(range(len(got)))
    pairs: list[tuple[dict, dict, int, int]] = []
    missed: list[dict] = []

    for want in expected:
        best_index, best_hit, best_total = None, -1, 0
        for i in remaining:
            if got[i].get("record_type") != want.get("record_type"):
                continue
            hit, total = field_score(want.get("fields", {}), got[i].get("fields", {}))
            if hit > best_hit:
                best_index, best_hit, best_total = i, hit, total
        if best_index is None:
            missed.append(want)
        else:
            remaining.remove(best_index)
            pairs.append((want, got[best_index], best_hit, best_total))

    return pairs, missed, [got[i] for i in remaining]


def run_cases(tenant_id, cases, limit=None, model=None) -> dict:
    from sqlalchemy import select

    from app.agents import Extractor
    from app.db import tenant_session
    from app.models.party import Party
    from app.models.tenant import BusinessProfile

    if model:
        Extractor.model_override = model
        print(f"model : {model}")

    results = []
    with tenant_session(tenant_id) as db:
        profile = db.execute(
            select(BusinessProfile).where(BusinessProfile.tenant_id == tenant_id)
        ).scalars().first()
        hints = list(
            db.execute(select(Party.name).where(Party.tenant_id == tenant_id).limit(40))
            .scalars().all()
        )
        agent = Extractor(db, tenant_id, profile)
        selected = cases[:limit] if limit else cases

        for index, case in enumerate(selected, start=1):
            expected = case["expect"]["records"]
            started = time.perf_counter()
            try:
                decision = agent.execute(
                    {
                        "body": render(case["messages"]),
                        "party_hints": hints,
                        "message_count": len(case["messages"]),
                    },
                    trace_id=uuid.uuid4(),
                )
                got = decision.output.get("records", [])
                error = None
            except Exception as exc:  # noqa: BLE001 - a failed call is a failed case
                got, error = [], str(exc)[:200]

            pairs, missed, spurious = pair_records(expected, got)
            hits = sum(p[2] for p in pairs)
            totals = sum(p[3] for p in pairs) + sum(
                len(m.get("fields", {})) for m in missed
            )

            results.append({
                "id": case["id"],
                "tags": case.get("tags", []),
                "messages": case["messages"],
                "expected": expected,
                "got": got,
                "matched": len(pairs),
                "missed": missed,
                "spurious": spurious,
                "field_hits": hits,
                "field_total": totals,
                "confidences": [r.get("confidence") for r in got],
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": error,
            })
            db.commit()
            mark = "ok " if not missed and not spurious else "MISS"
            print(f"  {index:>3}/{len(selected)} {mark} "
                  f"{len(got)} rec ({len(pairs)} matched, {len(missed)} missed, "
                  f"{len(spurious)} spurious)  [{case['id']}]")

    return summarise(results)


def summarise(results: list[dict]) -> dict:
    matched = sum(r["matched"] for r in results)
    missed = sum(len(r["missed"]) for r in results)
    spurious = sum(len(r["spurious"]) for r in results)
    hits = sum(r["field_hits"] for r in results)
    totals = sum(r["field_total"] for r in results)
    confidences = [c for r in results for c in r["confidences"] if c is not None]
    latencies = [r["latency_ms"] for r in results]

    per_type: dict[str, dict[str, int]] = {}
    for r in results:
        wanted = Counter(w["record_type"] for w in r["expected"])
        missed_types = Counter(m["record_type"] for m in r["missed"])
        for record_type, count in wanted.items():
            bucket = per_type.setdefault(record_type, {"expected": 0, "found": 0})
            bucket["expected"] += count
            bucket["found"] += count - missed_types.get(record_type, 0)

    spurious_types = Counter(
        s.get("record_type") for r in results for s in r["spurious"]
    )

    return {
        "cases": len(results),
        "clean_cases": sum(1 for r in results if not r["missed"] and not r["spurious"]),
        "expected_records": matched + missed,
        "matched": matched,
        "missed": missed,
        "spurious": spurious,
        "recall": round(matched / (matched + missed), 4) if (matched + missed) else 1.0,
        "precision": round(matched / (matched + spurious), 4) if (matched + spurious) else 1.0,
        "field_accuracy": round(hits / totals, 4) if totals else 0,
        "field_hits": hits,
        "field_total": totals,
        "errors": sum(1 for r in results if r["error"]),
        "median_confidence": round(statistics.median(confidences), 3) if confidences else None,
        "median_latency_ms": int(statistics.median(latencies)) if latencies else None,
        "per_type": per_type,
        "spurious_types": dict(spurious_types),
        "results": results,
    }


def report(s: dict) -> None:
    print()
    print(f"clean windows   : {s['clean_cases']}/{s['cases']} "
          f"({s['clean_cases'] / s['cases']:.1%})")
    print(f"recall          : {s['matched']}/{s['expected_records']} ({s['recall']:.1%})")
    print(f"precision       : {s['precision']:.1%}  ({s['spurious']} spurious)")
    print(f"field accuracy  : {s['field_hits']}/{s['field_total']} ({s['field_accuracy']:.1%})")
    print(f"median confidence: {s['median_confidence']}")
    print(f"median latency   : {s['median_latency_ms']} ms")

    print("\nby record type (found / expected)")
    for name, stat in sorted(s["per_type"].items()):
        print(f"  {name:<10} {stat['found']}/{stat['expected']}")
    if s["spurious_types"]:
        print("\nspurious records produced")
        for name, count in s["spurious_types"].items():
            print(f"  {name}: {count}")

    problems = [r for r in s["results"] if r["missed"] or r["spurious"]
                or r["field_hits"] < r["field_total"]]
    if problems:
        print(f"\nproblems ({len(problems)})")
        for r in problems:
            print(f"\n  [{r['id']}] {len(r['messages'])} messages")
            for m in r["missed"]:
                print(f"      MISSED   {m['record_type']} {m.get('fields', {})}")
            for sp in r["spurious"]:
                print(f"      SPURIOUS {sp.get('record_type')} "
                      f"{json.dumps(sp.get('fields', {}), ensure_ascii=False)[:110]}")
            for want, got, hit, total in _rezip(r):
                if hit < total:
                    for key, value in want.get("fields", {}).items():
                        actual = got.get("fields", {}).get(key)
                        same = (_lines_match(value, actual) if key == "lines"
                                else _norm(actual) == _norm(value))
                        if not same:
                            print(f"      FIELD    {key}: want {value!r}, got {actual!r}")
            if r["error"]:
                print(f"      ERROR    {r['error']}")


def _rezip(result: dict):
    """Re-pair a stored result so field-level misses can be printed."""
    pairs, _missed, _spurious = pair_records(result["expected"], result["got"])
    return pairs


def compare(current: dict, baseline: dict) -> None:
    print("\n" + "=" * 62)
    print("COMPARISON AGAINST BASELINE")
    print("=" * 62)
    for key, label in [("recall", "recall"), ("precision", "precision"),
                       ("field_accuracy", "field accuracy")]:
        delta = current[key] - baseline[key]
        print(f"{label:16s} {baseline[key]:.1%} -> {current[key]:.1%}  ({delta:+.1%})")

    before = {r["id"]: r for r in baseline["results"]}
    for r in current["results"]:
        was = before.get(r["id"])
        if not was:
            continue
        now_score = (-len(r["missed"]) - len(r["spurious"]), r["field_hits"])
        was_score = (-len(was["missed"]) - len(was["spurious"]), was["field_hits"])
        if now_score > was_score:
            print(f"  FIXED     [{r['id']}]")
        elif now_score < was_score:
            print(f"  REGRESSED [{r['id']}]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model")
    ap.add_argument("--save")
    ap.add_argument("--compare")
    ap.add_argument("--tag")
    args = ap.parse_args()

    cases = load_cases()
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]
    print(f"{len(cases)} windows\n")

    summary = run_cases(uuid.UUID(args.tenant), cases, args.limit, args.model)
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
