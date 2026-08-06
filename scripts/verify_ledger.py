"""Verification for section 4: ledger maths, exceptions, digest.

The ledger numbers get checked against Tally by someone who has been doing
this for thirty years, so they are tested with hand-worked arithmetic rather
than with whatever the code happens to produce.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_ledger.py
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.agents.digest as digest_module
from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Dispatch, Invoice, Order, OrderLine, Party, Payment, Quality
from app.models import Tenant
from app.services.auth import issue_token
from app.services.exceptions import rate_deviations, stalled_orders
from app.services.ledger import (
    ageing_buckets,
    bucket_labels,
    outstanding_by_party,
    overdue_crossings,
    party_ledger,
    payment_trend,
)

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


TODAY = date(2026, 8, 6)


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


TENANT = uuid.uuid4()

with admin_session() as db:
    tenant = Tenant(id=TENANT, business_name="Ledger Mills",
                    owner_phone=f"98{uuid.uuid4().int % 10**8:08d}",
                    owner_email="owner@example.com", locale="en")
    TOKEN = issue_token(tenant)
    db.add(tenant)

with tenant_session(TENANT) as db:
    db.add(BusinessProfile(
        tenant_id=TENANT, segments=["wholesaler"], modules={},
        vocabulary={}, rules={"overdue_days": 45, "rate_deviation_pct": 20}, examples=[],
    ))
    for name in ("Ashok Textiles", "Bharat Fabrics", "Kishore Silk", "Clean Payer"):
        db.add(Party(tenant_id=TENANT, name=name, phone=f"9{abs(hash(name)) % 10**9:09d}",
                     credit_days=45))

with tenant_session(TENANT) as db:
    ids = {p.name: p.id for p in db.query(Party).all()}

    # Ashok: 100000 invoiced 90 days ago, 40000 paid. 60000 open, 90 days late.
    db.add(Invoice(tenant_id=TENANT, party_id=ids["Ashok Textiles"], invoice_no="A1",
                   invoice_date=days_ago(90), due_date=days_ago(90), amount=100000))
    db.add(Payment(tenant_id=TENANT, party_id=ids["Ashok Textiles"], amount=40000,
                   received_on=days_ago(60), mode="neft"))

    # Bharat: two invoices, one payment that covers the first exactly.
    db.add(Invoice(tenant_id=TENANT, party_id=ids["Bharat Fabrics"], invoice_no="B1",
                   invoice_date=days_ago(50), due_date=days_ago(50), amount=25000))
    db.add(Invoice(tenant_id=TENANT, party_id=ids["Bharat Fabrics"], invoice_no="B2",
                   invoice_date=days_ago(10), due_date=days_ago(10), amount=30000))
    db.add(Payment(tenant_id=TENANT, party_id=ids["Bharat Fabrics"], amount=25000,
                   received_on=days_ago(40), mode="upi"))

    # Kishore: invoice not yet due, with tax.
    db.add(Invoice(tenant_id=TENANT, party_id=ids["Kishore Silk"], invoice_no="K1",
                   invoice_date=days_ago(5), due_date=TODAY + timedelta(days=20),
                   amount=10000, tax_amount=1800))

    # Clean Payer: overpaid — the surplus must be carried, not lost.
    db.add(Invoice(tenant_id=TENANT, party_id=ids["Clean Payer"], invoice_no="C1",
                   invoice_date=days_ago(20), due_date=days_ago(20), amount=5000))
    db.add(Payment(tenant_id=TENANT, party_id=ids["Clean Payer"], amount=8000,
                   received_on=days_ago(15), mode="cash"))

print("\n-- outstanding, worked by hand --")

with tenant_session(TENANT) as db:
    rows = {r["party_name"]: r for r in outstanding_by_party(db, TENANT, TODAY, 45)}

    check("ashok owes 100000 - 40000", rows["Ashok Textiles"]["outstanding"], 60000.0)
    check("  aged from the oldest unpaid bill", rows["Ashok Textiles"]["days_overdue"], 90)
    check("  and is overdue", rows["Ashok Textiles"]["is_overdue"], True)

    check("bharat's oldest bill was cleared exactly", rows["Bharat Fabrics"]["outstanding"], 30000.0)
    check("  so the age is the newer bill's", rows["Bharat Fabrics"]["days_overdue"], 10)
    check("  which is not yet overdue at 45 days", rows["Bharat Fabrics"]["is_overdue"], False)

    check("tax is part of what is owed", rows["Kishore Silk"]["outstanding"], 11800.0)
    check("  a bill not yet due is not overdue", rows["Kishore Silk"]["days_overdue"], 0)

    check("a fully paid party drops off the list", "Clean Payer" in rows, False)

    positions = {
        p.name: p for p in __import__("app.services.ledger", fromlist=["x"]).party_positions(
            db, TENANT, TODAY
        ).values()
    }
    check("overpayment is carried as credit, not lost",
          float(positions["Clean Payer"].unapplied_credit), 3000.0)

print("\n-- ageing buckets --")

with tenant_session(TENANT) as db:
    buckets = ageing_buckets(db, TENANT, TODAY, 45)
    check("the tenant's threshold is a boundary", "1-30" in buckets and "31-45" in buckets, True)
    check("not-yet-due money is separate", buckets["current"], 11800.0)
    check("ashok's 90 days lands in 61-90", buckets["61-90"], 60000.0)
    check("bharat's 10 days lands in 1-30", buckets["1-30"], 30000.0)
    check("buckets sum to total outstanding", round(sum(buckets.values()), 2), 101800.0)

    retail = bucket_labels(15)
    check("a retail threshold reshapes the buckets", retail[:3], ["current", "1-15", "16-30"])

print("\n-- overdue crossings are diff-based --")

with tenant_session(TENANT) as db:
    first = overdue_crossings(db, TENANT, TODAY, 45)
    check("day one reports no crossings, only history", first, [])

with tenant_session(TENANT) as db:
    again = overdue_crossings(db, TENANT, TODAY, 45)
    check("running twice reports nothing new", again, [])

# Bharat's second bill ages past 45 days.
LATER = TODAY + timedelta(days=40)
with tenant_session(TENANT) as db:
    crossed = overdue_crossings(db, TENANT, LATER, 45)
    check("a party that crosses is reported once", [c["party_name"] for c in crossed],
          ["Bharat Fabrics"])
    check("  with the amount", crossed[0]["outstanding"], 30000.0)
    check("  and the age", crossed[0]["days_overdue"], 50)

with tenant_session(TENANT) as db:
    check("and not reported again the next evening",
          overdue_crossings(db, TENANT, LATER + timedelta(days=1), 45), [])

with tenant_session(TENANT) as db:
    db.add(Payment(tenant_id=TENANT, party_id=ids["Bharat Fabrics"], amount=30000,
                   received_on=LATER, mode="neft"))

with tenant_session(TENANT) as db:
    check("paying up clears the flag",
          overdue_crossings(db, TENANT, LATER + timedelta(days=2), 45), [])
    rows = {r["party_name"]: r for r in outstanding_by_party(db, TENANT, LATER, 45)}
    check("  and the balance", "Bharat Fabrics" in rows, False)

print("\n-- party statement --")

with tenant_session(TENANT) as db:
    statement = party_ledger(db, TENANT, ids["Ashok Textiles"], TODAY)
    check("every document is listed", len(statement["entries"]), 2)
    check("running balance ends at what is owed", statement["closing_balance"], 60000.0)
    check("invoice is a debit", statement["entries"][0]["debit"], 100000.0)
    check("payment is a credit", statement["entries"][1]["credit"], 40000.0)

print("\n-- payment trend --")

with tenant_session(TENANT) as db:
    payer = Party(tenant_id=TENANT, name="Slowing Trader", credit_days=30)
    db.add(payer)
    db.flush()
    # Four settled bills: the first two on time, the last two three weeks late.
    for index, (age, lag) in enumerate([(170, 1), (150, 2), (60, 25), (30, 28)]):
        due = days_ago(age)
        db.add(Invoice(tenant_id=TENANT, party_id=payer.id, invoice_no=f"S{index}",
                       invoice_date=due, due_date=due, amount=10000))
        db.add(Payment(tenant_id=TENANT, party_id=payer.id, amount=10000,
                       received_on=due + timedelta(days=lag), mode="neft"))

with tenant_session(TENANT) as db:
    trend = payment_trend(db, TENANT, lookback_days=180)
    names = [t["party_name"] for t in trend]
    check("the slowing payer is flagged", names, ["Slowing Trader"])
    check("  by how much", trend[0]["slower_by_days"] > 14, True)
    check("steady payers are not flagged", "Ashok Textiles" in names, False)

print("\n-- exceptions --")

with tenant_session(TENANT) as db:
    quality = Quality(tenant_id=TENANT, code="SR-1042", name="SR-1042")
    db.add(quality)
    db.flush()

    # Three orders at ~62, one at 30 — the odd one out should be flagged.
    for index, rate in enumerate([62, 61, 63, 30]):
        order = Order(tenant_id=TENANT, party_id=ids["Ashok Textiles"], order_no=f"O{index}",
                      status="confirmed", order_date=days_ago(10 - index))
        db.add(order)
        db.flush()
        db.add(OrderLine(tenant_id=TENANT, order_id=order.id, quality_id=quality.id,
                         quantity=100, rate=rate, unit="meter"))

with tenant_session(TENANT) as db:
    flags = rate_deviations(db, TENANT, 20.0, TODAY)
    check("only the outlier is flagged", [f["rate"] for f in flags], [30.0])
    check("  compared against the usual rate", flags[0]["usual_rate"], 62.0)
    check("  and named as below", flags[0]["direction"], "below")

with tenant_session(TENANT) as db:
    late = Order(tenant_id=TENANT, party_id=ids["Ashok Textiles"], order_no="LATE",
                 status="confirmed", order_date=days_ago(30),
                 promised_date=days_ago(12))
    db.add(late)
    sent = Order(tenant_id=TENANT, party_id=ids["Ashok Textiles"], order_no="SENT",
                 status="confirmed", order_date=days_ago(30), promised_date=days_ago(12))
    db.add(sent)
    db.flush()
    db.add(Dispatch(tenant_id=TENANT, order_id=sent.id, lr_no="1", dispatched_on=days_ago(11)))

with tenant_session(TENANT) as db:
    stalled = stalled_orders(db, TENANT, TODAY)
    numbers = [s["order_no"] for s in stalled]
    check("an undispatched late order is flagged", "LATE" in numbers, True)
    check("  by how many days", next(s for s in stalled if s["order_no"] == "LATE")["late_by_days"],
          12)
    check("a dispatched order is not flagged", "SENT" in numbers, False)

# --- the API --------------------------------------------------------------

print("\n-- ledger api --")

from app.main import app  # noqa: E402

client = TestClient(app)
headers = {"Authorization": f"Bearer {TOKEN}"}

summary = client.get(f"/api/ledger/outstanding?as_of={TODAY}", headers=headers).json()
check("outstanding totals", summary["total_outstanding"], 101800.0)
check("  overdue subtotal", summary["total_overdue"], 60000.0)
check("  threshold reported", summary["overdue_days"], 45)

ageing = client.get(f"/api/ledger/ageing?as_of={TODAY}", headers=headers).json()
check("ageing totals match outstanding", ageing["total"], 101800.0)

statement = client.get(
    f"/api/ledger/party/{ids['Ashok Textiles']}?as_of={TODAY}", headers=headers
).json()
check("party statement balance", statement["closing_balance"], 60000.0)
check("a reminder is drafted, not sent", statement["reminder_link"].startswith("https://wa.me/"),
      True)
check("  with indian digit grouping", "60%2C000" in statement["reminder_link"], True)

flagged = client.get(f"/api/ledger/exceptions?as_of={TODAY}", headers=headers).json()
check("exceptions endpoint reports all three kinds",
      (len(flagged["rate_deviations"]) > 0, len(flagged["stalled_orders"]) > 0,
       len(flagged["slowing_payers"]) > 0), (True, True, True))

check("ledger needs a token", client.get("/api/ledger/outstanding").status_code, 401)

print("\n-- today screen shows it for real --")

digest_today = client.get("/api/today", headers=headers).json()
check("overdue is a real number now", digest_today["overdue"]["total"], 60000.0)
check("  with the worst party named", digest_today["overdue"]["worst_party"], "Ashok Textiles")
check("  and the tenant's threshold", digest_today["overdue"]["overdue_days"], 45)
check("exceptions are counted", digest_today["exceptions"]["total"] > 0, True)
check("  with a headline", bool(digest_today["exceptions"]["headline"]), True)
check("only low stock is still uncomputed", digest_today["unavailable"], ["low_stock"])

# --- the digest -----------------------------------------------------------

print("\n-- digest --")

composed = []


def fake_composer(*, model, system, user, **kwargs):
    composed.append(user)
    return (
        {"headline": "Rs 0 in today, 1 newly overdue",
         "sections": [{"title": "Money", "items": ["Ashok Textiles owes Rs 60,000"]}],
         "action_items": ["Chase Ashok Textiles"], "confidence": 1.0},
        {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001},
    )


digest_module.generate_json = fake_composer

resp = client.post(f"/api/jobs/digest?tenant_id={TENANT}&as_of={TODAY}", headers=headers)
check("digest job runs", resp.status_code, 200)
run = resp.json()
check("one tenant ran", run["ran"], 1)
result = run["results"][0]
check("composed by the agent", result["composed_by"], "digest_composer")
check("not emailed without smtp", result["emailed"], False)
check("  and says why", "SMTP" in result["detail"], True)
check("the model was handed the numbers, not asked for them",
      "60000" in composed[0] or "60000.0" in composed[0], True)

with tenant_session(TENANT) as db:
    from app.models import AgentRun
    check("the analyst run was logged",
          db.query(AgentRun).filter_by(agent="ledger_analyst").count() > 0, True)
    check("the composer run was logged",
          db.query(AgentRun).filter_by(agent="digest_composer").count(), 1)


def broken_composer(*args, **kwargs):
    raise RuntimeError("gemini down")


digest_module.generate_json = broken_composer
resp = client.post(f"/api/jobs/digest?tenant_id={TENANT}&as_of={TODAY}", headers=headers).json()
result = resp["results"][0]
check("a dead model does not stop the digest", result["composed_by"], "fallback")
check("  and it still has a headline", bool(result["headline"]), True)

digest_module.generate_json = fake_composer

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
