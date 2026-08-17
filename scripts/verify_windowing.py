"""Verification for section 1: conversation windows as the extraction unit.

Segmentation, stable keys, idempotent re-runs, and supersede-not-duplicate,
with the model stubbed so the plumbing is tested independently of accuracy.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_windowing.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta

import app.agents.extractor as extractor_module
from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Extraction, ExtractionWindow, Interaction, Order
from app.models import Party, Payment, Tenant
from app.services.backfill import run_backfill
from app.services.windowing import pending_windows, segment, sync_windows

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


BASE = datetime(2026, 6, 12, 9, 0)


def fake_extract(*, model, system, user, **kwargs):
    """Reads the rendered window; returns records the way the real model does."""
    usage = {"input_tokens": 400, "output_tokens": 90, "cost_usd": 0.0004}
    text = user.lower()
    records = []
    if "olive" in text:
        # The settled figure, not each request — the whole point of windowing.
        records.append({
            "record_type": "order", "confidence": 0.92, "reason": "",
            "source_lines": [1, 3],
            "fields": {"party": "Shree Krishna Textiles", "quality": "cotton slub",
                       "quantity": "1050", "unit": "m", "rate": "88"},
        })
    if "paid" in text:
        records.append({
            "record_type": "payment", "confidence": 0.95, "reason": "",
            "source_lines": [2],
            "fields": {"party": "Shree Krishna Textiles", "amount": "37440", "mode": "upi"},
        })
    if "defect" in text:
        records.append({
            "record_type": "complaint", "confidence": 0.9, "reason": "",
            "source_lines": [1],
            "fields": {"party": "Shree Krishna Textiles", "quality": "White", "quantity": "18"},
        })
    return {"records": records}, usage


extractor_module.generate_json = fake_extract

TENANT = uuid.uuid4()
with admin_session() as db:
    db.add(Tenant(id=TENANT, business_name="Window Mills",
                  owner_phone=f"98{uuid.uuid4().int % 10**8:08d}", paid_until=datetime.utcnow() + timedelta(days=365)))

with tenant_session(TENANT) as db:
    db.add(BusinessProfile(tenant_id=TENANT, segments=["wholesaler"], modules={},
                           vocabulary={"quantity_units": ["meter", "m"]},
                           rules={}, examples=[]))
    db.add(Party(tenant_id=TENANT, name="Shree Krishna Textiles"))


def add(body: str, minutes: int, thread: str = "chat", sender: str = "Shree Krishna Textiles"):
    with tenant_session(TENANT) as db:
        row = Interaction(tenant_id=TENANT, channel="whatsapp_export", sender=sender,
                          body=body, occurred_at=BASE + timedelta(minutes=minutes),
                          thread_key=thread)
        db.add(row)
        db.flush()
        return row.id


print("\n-- segmentation --")

add("Need 500 m White, 300 m Beige, 300 m Olive", 0)
add("Olive only 250 m ready", 2)
add("Okay make Olive 250. Total 1050 meters at 88", 4)
# Four hours later: a separate conversation.
add("Paid 37440 by UPI", 240)

with tenant_session(TENANT) as db:
    messages = db.query(Interaction).all()
    segments = segment(messages)
    check("a silence gap splits the conversation", len(segments), 2)
    check("  first window holds the order exchange", len(segments[0].messages), 3)
    check("  second holds the payment", len(segments[1].messages), 1)
    check("windows are keyed stably", segments[0].window_key(), segment(messages)[0].window_key())
    rendered = segments[0].render()
    check("rendered lines are numbered", rendered.startswith("[1] "), True)
    check("  and carry the sender", "Shree Krishna Textiles:" in rendered, True)
    check("line numbers map back to ids",
          segments[0].id_for_index(1), segments[0].messages[0].id)
    check("  out-of-range is ignored", segments[0].id_for_index(99), None)

with tenant_session(TENANT) as db:
    windows = sync_windows(db, TENANT)
    check("windows persisted", len(windows), 2)
    check("every message is assigned",
          db.query(Interaction).filter(Interaction.window_id.is_(None)).count(), 0)
    check("anchor recorded", windows[0].anchor_interaction_id is not None, True)

with tenant_session(TENANT) as db:
    before = {w.window_key for w in db.query(ExtractionWindow).all()}
    sync_windows(db, TENANT)
    after = {w.window_key for w in db.query(ExtractionWindow).all()}
    check("re-segmenting creates no new windows", after, before)

print("\n-- separate threads never merge --")

add("different chat entirely", 1, thread="other-chat", sender="Bharat Fabrics")
with tenant_session(TENANT) as db:
    sync_windows(db, TENANT)
    check("a second thread gets its own window",
          db.query(ExtractionWindow).count(), 3)

print("\n-- extraction over windows --")

run_backfill(TENANT, uuid.uuid4())

with tenant_session(TENANT) as db:
    extractions = db.query(Extraction).filter(Extraction.status != "superseded").all()
    types = sorted(e.record_type for e in extractions)
    check("one window yielded the settled order", types.count("order"), 1)
    check("  the other yielded the payment", types.count("payment"), 1)
    check("orders committed", db.query(Order).count(), 1)
    check("payments committed", db.query(Payment).count(), 1)

    order = db.query(Order).one()
    line = order.lines[0]
    check("the settled quantity was used, not the first ask", float(line.quantity), 1050.0)

    stored = db.query(Extraction).filter_by(record_type="order").first()
    check("record cites its source messages", len(stored.source_message_ids), 2)
    check("  and is tied to its window", stored.window_id is not None, True)

    windows = db.query(ExtractionWindow).all()
    check("all windows marked extracted",
          {w.outcome for w in windows}, {"extracted"})
    check("watermark caught up",
          all(w.extracted_hash == w.content_hash for w in windows), True)

print("\n-- re-running is a no-op --")

with tenant_session(TENANT) as db:
    check("nothing is pending", len(pending_windows(db, TENANT)), 0)

run_backfill(TENANT, uuid.uuid4())
with tenant_session(TENANT) as db:
    check("no duplicate orders", db.query(Order).count(), 1)
    check("no duplicate payments", db.query(Payment).count(), 1)
    check("no duplicate extractions",
          db.query(Extraction).filter(Extraction.status != "superseded").count(), 2)

print("\n-- a window that gains a message re-extracts and supersedes --")

add("Actually White roll 7 has weaving defect, around 18 m", 6)

with tenant_session(TENANT) as db:
    sync_windows(db, TENANT)
    pending = pending_windows(db, TENANT)
    check("only the changed window is pending", len(pending), 1)
    check("  and it now has four messages", pending[0].message_count, 4)

run_backfill(TENANT, uuid.uuid4())

with tenant_session(TENANT) as db:
    live = db.query(Extraction).filter(Extraction.status != "superseded").all()
    superseded = db.query(Extraction).filter_by(status="superseded").all()
    check("the old records were superseded, not duplicated", len(superseded), 1)
    check("  and the window's records replaced them",
          sorted(e.record_type for e in live), ["complaint", "order", "payment"])
    check("still exactly one order", db.query(Order).count(), 1)
    check("the complaint went to review, never auto-committed",
          db.query(Extraction).filter_by(record_type="complaint").one().status,
          "needs_review")

print("\n-- human work is never overwritten --")

with tenant_session(TENANT) as db:
    order_extraction = db.query(Extraction).filter_by(
        record_type="order", status="auto_committed"
    ).first()
    order_extraction.status = "corrected"  # stand in for the owner accepting it
    changed_window = order_extraction.window_id

add("and one more line to force a re-extract", 8)

run_backfill(TENANT, uuid.uuid4())

with tenant_session(TENANT) as db:
    window = db.get(ExtractionWindow, changed_window)
    check("the window is marked curated", window.outcome, "curated")
    check("  the owner's record survived",
          db.query(Extraction).filter_by(status="corrected").count(), 1)
    check("  and it was not superseded",
          db.query(Extraction).filter_by(record_type="order",
                                         status="superseded").count(), 1)

print("\n-- isolation --")

OTHER = uuid.uuid4()
with admin_session() as db:
    db.add(Tenant(id=OTHER, business_name="Other", owner_phone=f"97{uuid.uuid4().int % 10**8:08d}", paid_until=datetime.utcnow() + timedelta(days=365)))
with tenant_session(OTHER) as db:
    check("another tenant has no windows", db.query(ExtractionWindow).count(), 0)
    check("  and sync finds nothing to do", len(sync_windows(db, OTHER)), 0)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
