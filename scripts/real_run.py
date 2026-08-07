"""End-to-end onboarding + backfill against a live Gemini key.

The point is measurement, not a smoke test: every extraction is recorded with
its message, so the failures can be read verbatim rather than summarised.

    DATABASE_URL=... PYTHONPATH=. python scripts/real_run.py data/chat.txt

Writes var/real_run/ with per-message results and a summary.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.db import admin_session, tenant_session
from app.models import AgentRun, Extraction, Interaction, Order, Party, Payment, Tenant
from app.models.tenant import BusinessProfile
from app.services.auth import issue_token
from app.services.backfill import run_backfill
from app.services.intake import interactions_from_upload
from app.services.onboarding import build_profile
from app.services.party_import import import_parties, seeds_from_messages

OUT = Path("var/real_run")

# Trade messages are full of rupee signs and emoji; the Windows console
# defaults to cp1252 and would abort the run partway through printing them.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def main(path: Path, business: str = "Ravi Fabrics Surat",
         interview: str | None = None, out: Path | None = None) -> int:
    global OUT
    OUT = out or OUT
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()

    tenant_id = uuid.uuid4()
    with admin_session() as db:
        tenant = Tenant(
            id=tenant_id,
            business_name=business,
            owner_name="Ravi",
            owner_phone=f"98{uuid.uuid4().int % 10**8:08d}",
            city="Surat",
            locale="en",
            onboarded_at=datetime.utcnow(),
        )
        token = issue_token(tenant)
        db.add(tenant)

    print(f"tenant {tenant_id}")
    print(f"token  {token}\n")

    # 1. Ingest the export.
    job_id = uuid.uuid4()
    with tenant_session(tenant_id) as db:
        intake = interactions_from_upload(tenant_id, path.name, path, job_id)
        db.add_all(intake.interactions)
        db.flush()
        print(f"parsed {len(intake.interactions)} interactions "
              f"({intake.skipped} empty skipped)")

    # 2. Configure — a real Configurator call over the real sample.
    config_started = time.time()
    with tenant_session(tenant_id) as db:
        built = build_profile(db, tenant_id, interview or INTERVIEW, ["wholesaler"],
                              uuid.uuid4())
        db.add(BusinessProfile(
            tenant_id=tenant_id, segments=built["segments"], modules=built["modules"],
            vocabulary=built["vocabulary"], rules=built["rules"], examples=[],
        ))
    config_seconds = time.time() - config_started
    print(f"configurator: {built['source']} in {config_seconds:.1f}s")
    print(f"  modules   : {json.dumps(built['modules'])}")
    print(f"  vocabulary: {json.dumps(built['vocabulary'])}")
    print(f"  rules     : {json.dumps(built['rules'])}")
    if built.get("rationale"):
        print(f"  said      : {built['rationale']}")

    # 3. Seed parties, exactly as onboarding does.
    with tenant_session(tenant_id) as db:
        seeds = seeds_from_messages(db, tenant_id, None)
        result = import_parties(db, tenant_id, seeds, "messages")
        print(f"\nparties seeded: {result.created} "
              f"({', '.join(s.name for s in seeds)})")

    # 4. Backfill — one live extraction per conversation window, concurrently.
    print("\nbackfill running (live model calls, paced, concurrent)...")
    backfill_started = time.time()

    def progress(done: int, total: int, outcome: str) -> None:
        elapsed = time.time() - backfill_started
        filled = int(24 * done / max(total, 1))
        print(f"\r  [{'=' * filled:<24}] {done}/{total} windows  {elapsed:5.1f}s",
              end="", flush=True)

    run_backfill(tenant_id, job_id, on_progress=progress)
    backfill_seconds = time.time() - backfill_started
    print()

    # 5. Measure.
    with tenant_session(tenant_id) as db:
        rows = db.execute(
            select(Extraction, Interaction)
            .outerjoin(Interaction, Interaction.id == Extraction.interaction_id)
            .order_by(Extraction.created_at.asc())
        ).all()
        runs = db.execute(select(AgentRun)).scalars().all()
        orders = db.query(Order).count()
        payments = db.query(Payment).count()
        parties = db.query(Party).count()

        records = []
        for extraction, interaction in rows:
            records.append({
                "message": (interaction.body if interaction else "") or "",
                "sender": interaction.sender if interaction else None,
                "occurred_at": str(interaction.occurred_at) if interaction else None,
                "media": interaction.media_kind if interaction else None,
                "record_type": extraction.record_type,
                "status": extraction.status,
                "confidence": float(extraction.confidence or 0),
                "fields": extraction.payload or {},
                "reason": extraction.reason or "",
                "flags": (extraction.resolved or {}).get("flags", []),
                "party_id": (extraction.resolved or {}).get("party_id"),
                "method": (extraction.resolved or {}).get("method"),
                "pending_fields": list(extraction.pending_fields or []),
                "committed_type": extraction.committed_type,
            })

    (OUT / "records.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    extractor_runs = [r for r in runs if r.agent == "extractor"]
    latencies = sorted(r.latency_ms for r in extractor_runs if r.latency_ms)
    confidences = [float(r.confidence) for r in extractor_runs if r.confidence is not None]
    cost = sum(float(r.cost_usd or 0) for r in runs)
    tokens_in = sum(int(r.input_tokens or 0) for r in runs)
    tokens_out = sum(int(r.output_tokens or 0) for r in runs)
    errors = [r for r in runs if r.outcome == "error"]

    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for record in records:
        by_status[record["status"]] = by_status.get(record["status"], 0) + 1
        by_type[record["record_type"] or "none"] = by_type.get(record["record_type"] or "none", 0) + 1

    denominator = sum(v for k, v in by_status.items() if k != "rejected")
    committed = by_status.get("auto_committed", 0)
    queued = by_status.get("needs_review", 0)

    # What the owner actually has to do. A queued item that already exists as a
    # record with one blank is a very different amount of work from an empty
    # form, and the auto-commit rate alone cannot tell them apart.
    review_items = [r for r in records if r["status"] == "needs_review"]
    partial = [r for r in review_items if r["committed_type"]]

    summary = {
        "messages_parsed": len(records),
        "by_status": by_status,
        "by_record_type": by_type,
        "auto_commit_rate": round(committed / denominator, 3) if denominator else 0,
        "review_rate": round(queued / denominator, 3) if denominator else 0,
        "records_written": committed + len(partial),
        "written_rate": round((committed + len(partial)) / denominator, 3) if denominator else 0,
        "review_items_partial": len(partial),
        "fields_per_review_item": (
            round(sum(len(r["pending_fields"]) for r in partial) / len(partial), 2)
            if partial else None
        ),
        "orders_created": orders,
        "payments_created": payments,
        "parties": parties,
        "agent_runs": len(runs),
        "extractor_calls": len(extractor_runs),
        "errors": len(errors),
        "median_confidence": round(statistics.median(confidences), 3) if confidences else None,
        "mean_confidence": round(statistics.fmean(confidences), 3) if confidences else None,
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "p90_latency_ms": latencies[int(len(latencies) * 0.9)] if latencies else None,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost_usd": round(cost, 6),
        "configurator_seconds": round(config_seconds, 1),
        "backfill_seconds": round(backfill_seconds, 1),
        "wall_seconds": round(time.time() - started, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 62)
    for key, value in summary.items():
        print(f"{key:24s} {value}")
    print("=" * 62)

    if errors:
        print("\nERRORS")
        for run in errors:
            print(f"  [{run.agent}] {run.error}")
            print(f"    input: {(run.input_summary or '')[:200]}")

    return 0


INTERVIEW = """Segments the owner selected: wholesaler
What they sell: cotton and rayon fabric to garment manufacturers
Units they quote in: meter
Tracks dye lots: not stated
Gives credit: yes
Typical credit days: not stated
"""


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/example_whatsapp_chat.txt")
    ap.add_argument("--business", default="Ravi Fabrics Surat")
    ap.add_argument("--interview", help="file holding the interview answers")
    ap.add_argument("--out", default="var/real_run")
    args = ap.parse_args()

    text = Path(args.interview).read_text(encoding="utf-8") if args.interview else None
    raise SystemExit(main(Path(args.path), args.business, text, Path(args.out)))
