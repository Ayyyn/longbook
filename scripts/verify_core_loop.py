"""Verification for section 2: commit boundary, ingest, review queue.

Runs the whole loop against a live database with the Extractor swapped for a
deterministic stub, so it exercises the real Resolver, Triage, commit and API
without spending a Gemini call. Needs `httpx` (already present via the SDKs).

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_core_loop.py
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

import app.agents.extractor as extractor_module
from app.agents.extractor import UNREADABLE_FIELD_CEILING, coerce_number, normalise_fields
from app.db import admin_session, tenant_session
from app.models import (
    AgentRun, BusinessProfile, Extraction, Interaction, Order, Party, Payment, Tenant,
)
from app.services.auth import issue_token
from app.services.commit import accept_correction, commit_record, queue_for_review

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


# --- a stand-in for the model ---------------------------------------------


def fake_generate_json(*, model, system, user, **kwargs) -> tuple[dict, dict]:
    """Stands in for the Gemini call only.

    The real Extractor.run still executes around it — including the numeric
    normalisation — so the values it emits are exactly what production emits.
    Strings on purpose: this is the raw shape a model returns.
    """
    body = (user or "").lower()
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}

    if "rtgs" in body:
        return {"record_type": "payment", "confidence": 0.95, "reason": "",
                "fields": {"party": "Ashok Textiles", "amount": "50000", "mode": "neft"}}, usage
    if "mtr" in body:
        return {"record_type": "order", "confidence": 0.93, "reason": "",
                "fields": {"party": "Ashok Textiles", "quality": "SR-1042",
                           "quantity": "150", "unit": "meter", "rate": "62 nett"}}, usage
    if "lr no" in body:
        return {"record_type": "dispatch", "confidence": 0.91, "reason": "",
                "fields": {"party": "Ashok Textiles", "lr_no": "448821",
                           "transporter": "VRL"}}, usage
    if "kitna" in body:
        # Unknown party and a shaky read — this is what the queue is for.
        return {"record_type": "order", "confidence": 0.55,
                "reason": "Party and quality both unfamiliar.",
                "fields": {"party": "Naya Trader", "quality": "ZZ-9999",
                           "quantity": "20", "unit": "meter"}}, usage
    if "thoda" in body:
        # High confidence from the model, but the quantity is not a number.
        return {"record_type": "order", "confidence": 0.97, "reason": "",
                "fields": {"party": "Ashok Textiles", "quality": "SR-1042",
                           "quantity": "thoda sa", "unit": "meter"}}, usage
    return {"record_type": "noise", "confidence": 1.0, "reason": "", "fields": {}}, usage


extractor_module.generate_json = fake_generate_json

# --- fixtures -------------------------------------------------------------

TENANT = uuid.uuid4()
EXPORT = """[04/06/26, 10:12:03 AM] Ashok Bhai: Bhai 150 mtr SR-1042 blue chahiye, rate 62 nett
[04/06/26, 10:14:11 AM] Ashok Bhai: Good morning ji
[04/06/26, 11:02:45 AM] Ashok Bhai: aaj 50000 rtgs kar diya, check karo
[05/06/26, 09:30:00 AM] Ashok Bhai: LR no 448821 se bhej diya, transporter VRL
[05/06/26, 09:45:00 AM] +91 90000 11111: bhai ZZ-9999 ka rate kitna hai
[05/06/26, 10:00:00 AM] Ashok Bhai: SR-1042 thoda sa bhej dena
"""

seed = yaml.safe_load(Path("app/profiles/wholesaler.yaml").read_text(encoding="utf-8"))

with admin_session() as db:
    tenant = Tenant(id=TENANT, business_name="Verify Mills",
                    owner_phone=f"98{uuid.uuid4().int % 10**8:08d}")
    TOKEN = issue_token(tenant)
    db.add(tenant)

with tenant_session(TENANT) as db:
    db.add(BusinessProfile(tenant_id=TENANT, segments=seed["segments"], modules=seed["modules"],
                           vocabulary=seed["vocabulary"], rules=seed["rules"], examples=[]))
    db.add(Party(tenant_id=TENANT, name="Ashok Textiles", aliases=["Ashok Bhai"],
                 phone="+91 98765 43210"))

# --- numeric coercion -----------------------------------------------------

print("\n-- coerce_number --")

for label, raw, want in [
    ("plain string", "150", 150.0),
    ("int passthrough", 150, 150.0),
    ("float passthrough", 58.5, 58.5),
    ("indian grouping", "1,25,000", 125000.0),
    ("trailing shorthand", "62 nett", 62.0),
    ("unit suffix", "150 mtr", 150.0),
    ("currency prefix", "₹ 62.50", 62.5),
    ("negative", "-5", -5.0),
    ("not a number", "thoda sa", None),
    ("empty", "", None),
    ("none", None, None),
    ("bool is not a number", True, None),
]:
    check(label, coerce_number(raw), want)

print("\n-- normalise_fields --")

fields, unreadable = normalise_fields(
    {"quality": "SR-1042", "quantity": "150", "rate": "62 nett", "unit": "meter"}
)
check("numeric fields typed", (fields["quantity"], fields["rate"]), (150.0, 62.0))
check("non-numeric fields untouched", fields["quality"], "SR-1042")
check("nothing unreadable", unreadable, [])

fields, unreadable = normalise_fields({"quantity": "thoda sa", "rate": "62"})
check("unreadable becomes None", fields["quantity"], None)
check("  and is reported", unreadable, ["quantity"])

fields, unreadable = normalise_fields(
    {"lines": [{"quality": "A", "quantity": "10"}, {"quality": "B", "quantity": "paanch"}]}
)
check("lines are normalised too", fields["lines"][0]["quantity"], 10.0)
check("unreadable line field reported", unreadable, ["lines[1].quantity"])
check("empty string is not 'unreadable'", normalise_fields({"rate": ""})[1], [])

# --- media storage --------------------------------------------------------

print("\n-- store_media --")

import app.services.storage as storage_module  # noqa: E402
from app.config import settings  # noqa: E402
from app.services.storage import store_media  # noqa: E402

uri = store_media(TENANT, "voice.opus", b"fake-audio")
check("local fallback returns a file uri", uri.startswith("file://"), True)
check("  and the bytes are on disk",
      Path(uri.replace("file:///", "").replace("file://", "")).read_bytes(), b"fake-audio")
check("  under the tenant's prefix", str(TENANT) in uri, True)


class FakeBlob:
    def __init__(self):
        self.data = self.content_type = None

    def upload_from_string(self, data, content_type=None):
        self.data, self.content_type = data, content_type


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, key):
        self.blobs[key] = FakeBlob()
        return self.blobs[key]


fake_bucket = FakeBucket()
real_bucket = storage_module._bucket
settings().gcs_bucket = "textile-media"
storage_module._bucket = lambda: fake_bucket
try:
    uri = store_media(TENANT, "note.opus", b"voice-note-bytes")
    check("gcs uri returned when a bucket is set", uri.startswith("gs://textile-media/"), True)
    key = uri.removeprefix("gs://textile-media/")
    check("  uploaded the bytes", fake_bucket.blobs[key].data, b"voice-note-bytes")
    check("  with an audio content type", fake_bucket.blobs[key].content_type, "audio/ogg")
    check("  tenant-prefixed key", key.startswith(f"{TENANT}/"), True)

    photo = store_media(TENANT, "order.jpg", b"jpeg")
    check("  jpeg content type detected",
          fake_bucket.blobs[photo.removeprefix("gs://textile-media/")].content_type, "image/jpeg")
finally:
    settings().gcs_bucket = ""
    storage_module._bucket = real_bucket

# --- tokens ---------------------------------------------------------------

print("\n-- auth --")

from app.services.auth import hash_token, tenant_for_token  # noqa: E402

check("token is prefixed", TOKEN.startswith("tex_"), True)
check("token has real entropy", len(TOKEN) > 40, True)

with admin_session() as db:
    stored = db.get(Tenant, TENANT).api_token_hash
    check("only the digest is stored", stored, hash_token(TOKEN))
    check("  plaintext is nowhere in the row", TOKEN in str(stored), False)

    check("token resolves to its tenant", tenant_for_token(db, TOKEN), TENANT)
    check("wrong token resolves to nothing", tenant_for_token(db, "tex_wrong"), None)
    check("empty token resolves to nothing", tenant_for_token(db, ""), None)
    check("whitespace is tolerated", tenant_for_token(db, f"  {TOKEN}  "), TENANT)

    db.get(Tenant, TENANT).is_active = False
    db.flush()
    check("deactivated tenant cannot authenticate", tenant_for_token(db, TOKEN), None)
    db.get(Tenant, TENANT).is_active = True

# --- commit.py, directly --------------------------------------------------

print("\n-- commit_record --")


def state_for(record_type: str, fields: dict, confidence: float = 0.95, party=None) -> dict:
    return {
        "trace_id": uuid.uuid4(),
        "tenant_id": TENANT,
        "interaction": {"id": None, "channel": "whatsapp_export",
                        "occurred_at": datetime(2026, 6, 4, 10, 12)},
        "extraction": {"record_type": record_type, "fields": fields,
                       "confidence": confidence, "reason": ""},
        "resolution": {"party_id": party, "method": "alias"},
    }


with tenant_session(TENANT) as db:
    party = db.query(Party).filter_by(name="Ashok Textiles").one()

    res = commit_record(db, state_for("order", {"quality": "SR-1042", "quantity": "150",
                                                "unit": "meter", "rate": "62"}, party=party.id))
    check("order commits", (res["status"], res["record_type"], res["lines"]),
          ("committed", "order", 1))
    order = db.get(Order, uuid.UUID(res["id"]))
    check("order starts as draft", order.status, "draft")
    check("quality auto-created at high confidence", order.lines[0].quality_id is not None, True)
    check("quantity parsed", float(order.lines[0].quantity), 150.0)

    res = commit_record(db, state_for("order", {"quality": "SR-1042", "quantity": "150"},
                                      confidence=0.60, party=party.id))
    check("known quality still commits at low confidence", res["status"], "committed")

    res = commit_record(db, state_for("order", {"quality": "NEW-0001", "quantity": "10"},
                                      confidence=0.60, party=party.id))
    check("unknown quality at low confidence goes to review", res["status"], "needs_review")
    check("  and says why", res["flags"], ["unknown_quality(NEW-0001)"])

    res = commit_record(db, state_for("payment", {"amount": "1,25,000", "mode": "neft",
                                                  "reference": "UTR99"}, party=party.id))
    payment = db.get(Payment, uuid.UUID(res["id"]))
    check("indian digit grouping parsed", float(payment.amount), 125000.0)

    res = commit_record(db, state_for("payment", {"mode": "cash"}, party=party.id))
    check("payment without amount goes to review", res["flags"], ["missing_amount"])

    res = commit_record(db, state_for("dispatch", {"lr_no": "448821", "transporter": "VRL"},
                                      party=party.id))
    check("dispatch commits", res["record_type"], "dispatch")

    res = commit_record(db, state_for("order", {"quality": "SR-1042", "quantity": "5"}))
    check("no party goes to review", res["flags"], ["unresolved_party"])

    res = commit_record(db, state_for("noise", {}))
    check("noise is discarded", res["status"], "discarded")

    res = commit_record(db, state_for("enquiry", {"quality": "SR-1042"}, party=party.id))
    check("enquiry is logged, not written", res["status"], "logged")

    res = queue_for_review(db, state_for("order", {"quantity": "9"}, party=party.id), flags=["x"])
    check("queue_for_review persists needs_review", res["status"], "needs_review")

# --- accept_correction ----------------------------------------------------

print("\n-- accept_correction --")

with tenant_session(TENANT) as db:
    interaction = Interaction(tenant_id=TENANT, channel="whatsapp_export",
                              body="200 mtr SR-1042 @ 65", occurred_at=datetime(2026, 6, 6, 9, 0))
    db.add(interaction)
    db.flush()
    queued = queue_for_review(
        db,
        {**state_for("order", {"quality": "SR-1042", "quantity": "20"}, confidence=0.5,
                     party=party.id),
         "interaction": {"id": interaction.id, "channel": "whatsapp_export"}},
    )
    extraction_id = uuid.UUID(queued["extraction_id"])

with tenant_session(TENANT) as db:
    result = accept_correction(db, extraction_id,
                               {"fields": {"quality": "SR-1042", "quantity": "200", "rate": "65"}})
    check("correction commits", result["status"], "corrected")
    order = db.get(Order, uuid.UUID(result["id"]))
    check("corrected order is confirmed, not draft", order.status, "confirmed")
    check("corrected quantity used", float(order.lines[0].quantity), 200.0)

    profile = db.query(BusinessProfile).filter_by(tenant_id=TENANT).one()
    check("example harvested", len(profile.examples), 1)
    check("  input is the original message", profile.examples[0]["input"], "200 mtr SR-1042 @ 65")
    check("  output is the correction", profile.examples[0]["output"]["fields"]["quantity"], "200")

    stored = db.query(Extraction).filter_by(id=extraction_id).one()
    check("extraction points at what it produced", str(stored.committed_id), result["id"])
    check("trace_id is a column, not JSONB", stored.trace_id is not None, True)
    check("  and is gone from resolved", "trace_id" in (stored.resolved or {}), False)

print("\n-- examples cap --")

with tenant_session(TENANT) as db:
    profile = db.query(BusinessProfile).filter_by(tenant_id=TENANT).one()
    profile.examples = [{"input": f"old {i}", "output": {}} for i in range(40)]

with tenant_session(TENANT) as db:
    interaction = Interaction(tenant_id=TENANT, body="fresh correction message")
    db.add(interaction)
    db.flush()
    queued = queue_for_review(
        db,
        {**state_for("payment", {"amount": "10"}, confidence=0.4, party=party.id),
         "interaction": {"id": interaction.id, "channel": "whatsapp_export"}},
    )
    eid = uuid.UUID(queued["extraction_id"])

with tenant_session(TENANT) as db:
    accept_correction(db, eid, {"fields": {"amount": "999", "mode": "cash"}})
    profile = db.query(BusinessProfile).filter_by(tenant_id=TENANT).one()
    check("capped at 40", len(profile.examples), 40)
    check("oldest dropped", profile.examples[0]["input"], "old 1")
    check("newest kept", profile.examples[-1]["input"], "fresh correction message")

# --- the API --------------------------------------------------------------

print("\n-- ingest + review API --")

from app.main import app  # noqa: E402 - imported after the Extractor swap

client = TestClient(app)
headers = {"Authorization": f"Bearer {TOKEN}"}

resp = client.post("/api/ingest", headers=headers,
                   files={"file": ("chat.txt", EXPORT.encode(), "text/plain")})
check("upload accepted", resp.status_code, 202)
body = resp.json()
check("all six messages stored", body["interactions"], 6)
job_id = body["job_id"]

status = client.get(f"/api/ingest/jobs/{job_id}", headers=headers).json()
check("job completed", status["state"], "done")
check("every message processed", status["processed"], 6)
check("three auto-committed", status["committed"], 3)
check("two need review", status["needs_review"], 2)
check("one discarded as noise", status["discarded"], 1)
check("no errors", status["errors"], [])

unreadable = [
    i for i in client.get("/api/review/queue", headers=headers).json()["items"]
    if i["message"] and "thoda" in i["message"]
]
check("unreadable quantity went to review despite 0.97", len(unreadable), 1)
check("  confidence was pulled down", unreadable[0]["confidence"], UNREADABLE_FIELD_CEILING)
check("  field left blank for the owner", unreadable[0]["fields"]["quantity"], None)
check("  and the reason says which field", "quantity" in unreadable[0]["reason"], True)

queue = client.get("/api/review/queue", headers=headers).json()
pending = [i for i in queue["items"] if i["message"] and "kitna" in i["message"]]
check("queued item is on the queue", len(pending), 1)
item = pending[0]
check("  carries the original message", "ZZ-9999" in item["message"], True)
check("  carries the agent's doubt", bool(item["reason"]), True)
check("  suggests creating the unknown party", item["suggest_create"], "Naya Trader")

corrected = client.post(
    f"/api/review/{item['extraction_id']}/correct",
    headers=headers,
    json={"record_type": "enquiry", "fields": {"quality": "ZZ-9999"},
          "party_name": "Naya Trader"},
).json()
check("correct returns corrected", corrected["status"], "corrected")
check("queue item exposes its trace", item["trace_id"] is not None, True)

with tenant_session(TENANT) as db:
    check("party created from the correction",
          db.query(Party).filter_by(name="Naya Trader").count(), 1)

    # The whole point of the column: Agent Activity is a join.
    runs = db.query(AgentRun).filter_by(trace_id=uuid.UUID(item["trace_id"])).all()
    check("every agent run behind the item is reachable by trace", len(runs) >= 2, True)
    check("  and all are flagged as human-overridden",
          [r.human_override for r in runs], [True] * len(runs))
    check("  with a review timestamp", all(r.reviewed_at is not None for r in runs), True)

check("item leaves the queue",
      len(client.get("/api/review/queue", headers=headers).json()["items"]),
      queue["total"] - 1)

check("re-accepting a closed item is a conflict",
      client.post(f"/api/review/{item['extraction_id']}/accept", headers=headers).status_code, 409)

resp = client.post("/api/ingest", headers=headers,
                   files={"file": ("book.pdf", b"%PDF-", "application/pdf")})
check("unsupported type rejected", resp.status_code, 415)

check("unknown token rejected",
      client.get("/api/review/queue", headers={"Authorization": "Bearer tex_nonsense"}).status_code,
      401)
check("missing token rejected", client.get("/api/review/queue").status_code, 401)
check("  with a bearer challenge",
      client.get("/api/review/queue").headers.get("www-authenticate"), "Bearer")
check("tenant id header alone is not enough",
      client.get("/api/review/queue", headers={"X-Tenant-Id": str(TENANT)}).status_code, 401)

print("\n-- today --")

from datetime import date  # noqa: E402

with tenant_session(TENANT) as db:
    party = db.query(Party).filter_by(name="Ashok Textiles").one()
    commit_record(db, {
        "trace_id": uuid.uuid4(),
        "tenant_id": TENANT,
        "interaction": {"id": None, "channel": "manual"},
        "extraction": {"record_type": "payment", "confidence": 0.99, "reason": "",
                       "fields": {"amount": "2,50,000", "mode": "upi",
                                  "received_on": date.today().isoformat()}},
        "resolution": {"party_id": party.id, "method": "alias"},
    })

digest = client.get("/api/today", headers=headers).json()
check("money in today", digest["money_in"]["today"], 250000.0)
check("one payment today", digest["money_in"]["payments_today"], 1)
check("week total includes it", digest["money_in"]["last_7_days"], 250000.0)
check("open orders counted", digest["orders"]["open_total"] >= 1, True)
check("drafts flagged for confirmation", digest["orders"]["awaiting_confirmation"] >= 1, True)
check("review count matches the queue",
      digest["needs_review"],
      client.get("/api/review/queue", headers=headers).json()["total"])
check("agent decisions counted", digest["agent_decisions_today"] > 0, True)
check("recent payments listed", digest["recent_payments"][0]["amount"], 250000.0)
check("  with the party name", digest["recent_payments"][0]["party_name"], "Ashok Textiles")
check("overdue is computed now", "newly_overdue" in digest["unavailable"], False)
check("stock is still named, not zeroed", digest["unavailable"], ["low_stock"])
check("today needs a token", client.get("/api/today").status_code, 401)

print("\n-- re-running a finished job --")

from app.services.backfill import run_backfill  # noqa: E402

with tenant_session(TENANT) as db:
    orders_before = db.query(Order).count()

run_backfill(TENANT, uuid.UUID(job_id))
again = client.get(f"/api/ingest/jobs/{job_id}", headers=headers).json()
check("still six processed, not twelve", again["processed"], 6)
with tenant_session(TENANT) as db:
    check("no duplicate orders", db.query(Order).count(), orders_before)

# --- isolation still holds across the API --------------------------------

print("\n-- isolation --")

OTHER = uuid.uuid4()
with admin_session() as db:
    other = Tenant(id=OTHER, business_name="Other Mills",
                   owner_phone=f"97{uuid.uuid4().int % 10**8:08d}")
    OTHER_TOKEN = issue_token(other)
    db.add(other)
with tenant_session(OTHER) as db:
    db.add(BusinessProfile(tenant_id=OTHER, segments=[], modules={}, vocabulary={}, rules={},
                           examples=[]))

other_headers = {"Authorization": f"Bearer {OTHER_TOKEN}"}
other_queue = client.get("/api/review/queue", headers=other_headers).json()
check("another tenant sees an empty queue", other_queue["total"], 0)
check("another tenant cannot fetch our extraction",
      client.get(f"/api/review/{item['extraction_id']}",
                 headers=other_headers).status_code, 404)
check("another tenant cannot see our job",
      client.get(f"/api/ingest/jobs/{job_id}", headers=other_headers).status_code,
      404)

# The checks above would pass on explicit .where() clauses alone. This one only
# passes if the session guard itself is live: no tenant filter is written here.
from app.api.deps import tenant_db  # noqa: E402
from app.db import session_tenant  # noqa: E402

with tenant_session(TENANT) as db:
    our_interaction = db.query(Interaction).first().id

gen = tenant_db(OTHER)
scoped = next(gen)
check("dependency session carries the tenant", session_tenant(scoped), OTHER)
check("unfiltered get() is still filtered", scoped.get(Interaction, our_interaction), None)
with tenant_session(TENANT) as db:
    check("  and the owner can still read it", db.get(Interaction, our_interaction).id,
          our_interaction)
gen.close()

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
