"""Verification for section 2: validation, field-level gating, risk weighting.

The case that motivated it: a payment carrying a party, a UTR and a date but no
amount. Under record-level gating the owner got an empty form. Here the record
is written, the amount is left blank, the ledger ignores it, and the owner is
asked one question.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_gating.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

import app.agents.extractor as extractor_module
from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Extraction, Invoice, Party, Payment, Tenant
from app.services.auth import issue_token
from app.services.backfill import run_backfill
from app.services.gating import gate_record, strip_pending
from app.services.ledger import outstanding_by_party
from app.services.validation import (
    check_line_arithmetic,
    check_unit,
    money_rule_failed,
    validate,
)

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


TODAY = date.today()
BASE = datetime(2026, 6, 12, 9, 0)

# --- 2a: deterministic validation, no database needed ---------------------

print("\n-- arithmetic --")

good = check_line_arithmetic({"lines": [{"quantity": 500, "rate": 88},
                                        {"quantity": 550, "rate": 88}], "amount": 92400})
check("lines reconciling to the stated total pass", good.status, "pass")

bad = check_line_arithmetic({"lines": [{"quantity": 500, "rate": 88}], "amount": 92400})
check("lines that do not reconcile fail", bad.status, "fail")
check("  and the failure names the money fields", "amount" in bad.fields, True)
check("  and it is flagged as touching money", bad.touches_money, True)

check("a missing total is not_applicable, never a silent pass",
      check_line_arithmetic({"lines": [{"quantity": 5, "rate": 2}]}).status, "not_applicable")
check("a missing rate is not_applicable",
      check_line_arithmetic({"lines": [{"quantity": 5}], "amount": 10}).status,
      "not_applicable")
check("rounding inside 2% is tolerated",
      check_line_arithmetic({"lines": [{"quantity": 100, "rate": 62}], "amount": 6250}).status,
      "pass")


class FakeProfile:
    vocabulary = {"quantity_units": ["meter", "thaan"]}
    rules = {}
    examples = []


print("\n-- units --")

check("a known unit passes", check_unit(FakeProfile(), {"unit": "meter"}).status, "pass")
check("an abbreviation is the same unit", check_unit(FakeProfile(), {"unit": "mtr"}).status,
      "pass")
check("an unknown unit fails", check_unit(FakeProfile(), {"unit": "gallon"}).status, "fail")
check("no unit stated is not_applicable", check_unit(FakeProfile(), {}).status, "not_applicable")

# --- 2b: field-level gating, in isolation ---------------------------------

print("\n-- gating --")

payment = {
    "record_type": "payment",
    "fields": {"reference": "56293819271", "mode": "upi", "received_on": "2026-07-05"},
    "resolution": {"party_id": uuid.uuid4()},
}
gate = gate_record(payment, [], confidence=1.0, floor=0.85)
check("a payment with no amount is not fully committable", gate.committable, False)
check("  and only the amount is pending", gate.pending, ["amount"])
check("  which is recognised as a money block", gate.blocks_money, True)
check("  with a reason the owner can read",
      gate.reasons["amount"], "not stated in the conversation")

complete = {**payment, "fields": {**payment["fields"], "amount": 37440}}
check("a complete payment commits outright",
      gate_record(complete, [], confidence=1.0, floor=0.85).committable, True)

no_party = {**complete, "resolution": {}}
check("an unresolved party is pending",
      gate_record(no_party, [], confidence=1.0, floor=0.85).pending, ["party"])

order = {
    "record_type": "order",
    "fields": {"lines": [{"quality": "SR-1042", "quantity": 500, "rate": 88}]},
    "resolution": {"party_id": uuid.uuid4()},
}
check("quantity inside lines counts as present",
      gate_record(order, [], confidence=1.0, floor=0.85).committable, True)

low = gate_record(order, [], confidence=0.5, floor=0.85)
check("below the floor everything asserted is up for review", "quantity" in low.pending, True)

check("stripping removes only the pending fields",
      strip_pending({"amount": 5, "mode": "upi"}, ["amount"]), {"mode": "upi"})
check("  including inside lines",
      strip_pending({"lines": [{"quantity": 5, "rate": 9}]}, ["rate"]),
      {"lines": [{"quantity": 5}]})

# --- the end-to-end case --------------------------------------------------

print("\n-- the payment-with-no-amount case, end to end --")


def fake_extract(*, model, system, user, **kwargs):
    usage = {"input_tokens": 400, "output_tokens": 90, "cost_usd": 0.0004}
    text = (user or "").lower()
    records = []
    if "utr" in text:
        # Exactly the real-run failure: party, reference and date, no amount.
        records.append({
            "record_type": "payment", "confidence": 1.0, "reason": "", "source_lines": [1],
            "fields": {"party": "Shree Krishna Textiles", "reference": "56293819271",
                       "mode": "upi", "received_on": TODAY.isoformat()},
        })
    if "big order" in text:
        records.append({
            "record_type": "order", "confidence": 0.88, "reason": "", "source_lines": [1],
            "fields": {"party": "Shree Krishna Textiles", "quality": "SR-1042",
                       "quantity": 5000, "unit": "meter", "rate": 88},
        })
    return {"records": records}, usage


extractor_module.generate_json = fake_extract

TENANT = uuid.uuid4()
with admin_session() as db:
    tenant = Tenant(id=TENANT, business_name="Gating Mills",
                    owner_phone=f"98{uuid.uuid4().int % 10**8:08d}")
    TOKEN = issue_token(tenant)
    db.add(tenant)

with tenant_session(TENANT) as db:
    db.add(BusinessProfile(
        tenant_id=TENANT, segments=["wholesaler"], modules={},
        vocabulary={"quantity_units": ["meter", "thaan"]},
        rules={"overdue_days": 45, "high_value_amount": 100000}, examples=[],
    ))
    db.add(Party(tenant_id=TENANT, name="Shree Krishna Textiles"))

with tenant_session(TENANT) as db:
    party = db.query(Party).one()
    db.add(Invoice(tenant_id=TENANT, party_id=party.id, invoice_no="INV-1",
                   invoice_date=TODAY - timedelta(days=60),
                   due_date=TODAY - timedelta(days=60), amount=100000))
    db.add(__import__("app.models", fromlist=["Interaction"]).Interaction(
        tenant_id=TENANT, channel="whatsapp_export", sender="Shree Krishna Textiles",
        body="Paid full. UTR 56293819271", occurred_at=BASE, thread_key="chat"))

before = None
with tenant_session(TENANT) as db:
    before = outstanding_by_party(db, TENANT, TODAY, 45)[0]["outstanding"]

run_backfill(TENANT, uuid.uuid4())

with tenant_session(TENANT) as db:
    payments = db.query(Payment).all()
    check("the payment WAS written", len(payments), 1)
    row = payments[0]
    check("  with the party the owner already knows", row.party_id, party.id)
    check("  and the UTR", row.reference, "56293819271")
    check("  and the mode", row.mode, "upi")
    check("  but no amount", row.amount, None)
    check("  and it is marked as awaiting one field",
          row.attributes.get("pending_fields"), ["amount"])

    extraction = db.query(Extraction).filter_by(record_type="payment").one()
    check("it sits in the queue", extraction.status, "needs_review")
    check("  asking only for the amount", extraction.pending_fields, ["amount"])
    check("  and it points at the record it wrote", str(extraction.committed_id), str(row.id))
    check("  with its validation results recorded",
          all("status" in v for v in extraction.validations), True)

    after = outstanding_by_party(db, TENANT, TODAY, 45)[0]["outstanding"]
    check("the half-known payment does NOT move the ledger", after, before)

print("\n-- the owner answers the one question --")

client = TestClient(__import__("app.main", fromlist=["app"]).app)
headers = {"Authorization": f"Bearer {TOKEN}"}

queue = client.get("/api/review/queue", headers=headers).json()
item = next(i for i in queue["items"] if i["record_type"] == "payment")
check("the screen is told what to ask for", item["pending_fields"], ["amount"])
check("  and why", bool(item["pending_reasons"].get("amount")), True)
check("  and shows what is already committed", item["fields"]["reference"], "56293819271")
check("  and which record it belongs to", item["committed_type"], "payment")

resp = client.post(f"/api/review/{item['extraction_id']}/correct", headers=headers,
                   json={"fields": {**item["fields"], "amount": 60000}})
check("answering succeeds", resp.status_code, 200)

with tenant_session(TENANT) as db:
    check("still exactly one payment, not a duplicate", db.query(Payment).count(), 1)
    row = db.query(Payment).one()
    check("  now carrying the amount", float(row.amount), 60000.0)
    check("  and no longer pending", row.attributes.get("pending_fields"), None)
    check("  the UTR survived", row.reference, "56293819271")

    after = outstanding_by_party(db, TENANT, TODAY, 45)[0]["outstanding"]
    check("and now it moves the ledger", after, before - 60000.0)

# --- 2d: risk weighting ---------------------------------------------------

print("\n-- risk weighting --")

with tenant_session(TENANT) as db:
    from app.agents import Triage

    profile = db.query(BusinessProfile).one()
    triage = Triage(db, TENANT, profile)
    party_id = db.query(Party).one().id

    small = {
        "record_type": "order", "confidence": 0.86, "party_id": party_id,
        "quantity": 10, "rate": 88,
        "record": {"record_type": "order", "resolution": {"party_id": party_id},
                   "fields": {"quality": "SR-1042", "quantity": 10, "unit": "meter",
                              "rate": 88}},
    }
    check("a small order clears 0.85", triage.run(small).output["action"], "commit")

    big = {
        **small, "quantity": 5000,
        "record": {**small["record"],
                   "fields": {**small["record"]["fields"], "quantity": 5000}},
    }
    decision = triage.run(big)
    check("the same confidence on a high-value order does not",
          decision.output["action"], "review")
    check("  and it says why",
          any("high_value" in f for f in decision.output["flags"]), True)

    enquiry = {
        "record_type": "enquiry", "confidence": 0.75, "party_id": party_id,
        "record": {"record_type": "enquiry", "resolution": {"party_id": party_id},
                   "fields": {"quality": "SR-1042", "unit": "meter"}},
    }
    check("a low-stakes enquiry commits below the floor",
          triage.run(enquiry).output["action"], "commit")

    broken = {
        "record_type": "order", "confidence": 1.0, "party_id": party_id,
        "record": {"record_type": "order", "resolution": {"party_id": party_id},
                   "fields": {"quality": "SR-1042", "quantity": 500, "unit": "meter",
                              "rate": 88, "amount": 999999}},
    }
    decision = triage.run(broken)
    check("a failed money check overrides full confidence",
          decision.output["action"], "review")
    check("  named in the flags",
          any("line_arithmetic" in f for f in decision.output["flags"]), True)

    unknown_unit = {
        "record_type": "order", "confidence": 1.0, "party_id": party_id,
        "record": {"record_type": "order", "resolution": {"party_id": party_id},
                   "fields": {"quality": "SR-1042", "quantity": 5, "unit": "gallon"}},
    }
    check("an unknown unit is queued as a field, not a whole record",
          unknown_unit and triage.run(unknown_unit).output["pending_fields"], ["unit"])

print("\n-- validation is recorded, never silently skipped --")

with tenant_session(TENANT) as db:
    results = validate(db, TENANT, profile, {
        "record_type": "order",
        "resolution": {"party_id": party_id},
        "fields": {"quality": "SR-1042", "quantity": 5, "unit": "meter"},
    })
    statuses = {r.rule: r.status for r in results}
    check("every applicable rule reported", "party_known" in statuses, True)
    check("  arithmetic with nothing to check is not_applicable",
          statuses["line_arithmetic"], "not_applicable")
    check("  and rate band with no history is not_applicable",
          statuses["rate_band"], "not_applicable")
    check("no money rule failed here", money_rule_failed(results), False)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
