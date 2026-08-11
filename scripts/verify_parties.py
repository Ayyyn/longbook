"""Verification for section 4: party memory, and the Parties/Orders APIs.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_parties.py
"""

from __future__ import annotations

import sys
import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.db import admin_session, tenant_session
from app.models import (
    BusinessProfile,
    Extraction,
    Invoice,
    Order,
    OrderLine,
    Party,
    Payment,
    Item,
    Tenant,
)
from app.services.auth import issue_token
from app.services.party_brief import (
    as_prompt_context,
    refresh_party,
    refresh_stale,
    reminder_facts,
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


def ago(days: int) -> date:
    return TODAY - timedelta(days=days)


TENANT = uuid.uuid4()
with admin_session() as db:
    tenant = Tenant(id=TENANT, business_name="Memory Mills",
                    owner_phone=f"98{uuid.uuid4().int % 10**8:08d}")
    TOKEN = issue_token(tenant)
    db.add(tenant)

with tenant_session(TENANT) as db:
    db.add(BusinessProfile(tenant_id=TENANT, segments=["wholesaler"], modules={},
                           vocabulary={"quantity_units": ["meter"]},
                           rules={"overdue_days": 45}, examples=[]))
    db.add(Party(tenant_id=TENANT, name="Ashok Textiles", phone="9876543210",
                 city="Surat", credit_days=30))
    db.add(Party(tenant_id=TENANT, name="Quiet Trader", phone="9000000000"))

with tenant_session(TENANT) as db:
    party = db.query(Party).filter_by(name="Ashok Textiles").one()
    quality = Item(tenant_id=TENANT, code="SR-1042", name="SR-1042")
    other = Item(tenant_id=TENANT, code="SR-1188", name="SR-1188")
    db.add_all([quality, other])
    db.flush()

    # Three orders of SR-1042 and one of SR-1188 — a clear preference.
    for index, (code, rate) in enumerate(
        [(quality, 60), (quality, 62), (quality, 64), (other, 90)]
    ):
        order = Order(tenant_id=TENANT, party_id=party.id, order_no=f"O{index}",
                      status="confirmed", order_date=ago(60 - index * 10))
        db.add(order)
        db.flush()
        db.add(OrderLine(tenant_id=TENANT, order_id=order.id, item_id=code.id,
                         quantity=100, unit="meter", rate=rate))

    # Two settled bills, both paid late, so the behaviour is measurable.
    for index, (age, lag) in enumerate([(90, 20), (60, 25)]):
        due = ago(age)
        db.add(Invoice(tenant_id=TENANT, party_id=party.id, invoice_no=f"INV-{index}",
                       invoice_date=due, due_date=due, amount=50000))
        db.add(Payment(tenant_id=TENANT, party_id=party.id, amount=50000,
                       received_on=due + timedelta(days=lag), mode="neft"))
    # And one still open.
    db.add(Invoice(tenant_id=TENANT, party_id=party.id, invoice_no="INV-OPEN",
                   invoice_date=ago(70), due_date=ago(70), amount=80000))

    db.add(Extraction(tenant_id=TENANT, record_type="complaint", status="corrected",
                      payload={"notes": "Roll 7 weaving defect", "quality": "SR-1042"},
                      resolved={"party_id": str(party.id)}, confidence=0.9))

print("\n-- the brief --")

with tenant_session(TENANT) as db:
    party = db.query(Party).filter_by(name="Ashok Textiles").one()
    brief = refresh_party(db, TENANT, party.id)

    check("what they buy, most frequent first", brief["buys"][0]["quality"], "SR-1042")
    check("  counted", brief["buys"][0]["times"], 3)
    check("  and the second quality is there too", len(brief["buys"]), 2)

    band = brief["rate_band"]
    check("rate band low", band["low"], 60.0)
    check("rate band typical", band["typical"], 63.0)
    check("rate band high", band["high"], 90.0)
    check("  with an observation count", band["observations"], 4)

    behaviour = brief["payment_behaviour"]
    # FIFO: the first payment clears INV-0; the second lands on the older
    # INV-OPEN and only part-pays it, so only one bill is actually settled.
    check("settlements counted", behaviour["settlements"], 1)
    check("average days to settle", behaviour["avg_days_to_settle"], 20.0)
    check("terms on paper recorded", behaviour["terms_days"], 30)
    check("outstanding carried", behaviour["outstanding"], 80000.0)
    check("preferred payment mode", behaviour["modes"][0]["mode"], "neft")

    check("complaint history", brief["complaints"]["count"], 1)
    check("  with what it was about",
          "weaving defect" in brief["complaints"]["recent"][0]["what"], True)

    check("contact carried", brief["contact"]["phone"], "9876543210")
    check("order total", brief["totals"]["orders"], 4)
    check("last order date recorded", brief["totals"]["last_order_on"] is not None, True)

    check("claims are traceable to records", len(brief["sources"]["orders"]) > 0, True)
    check("brief is stamped", brief["generated_at"] is not None, True)

print("\n-- derived from committed records only --")

with tenant_session(TENANT) as db:
    party = db.query(Party).filter_by(name="Ashok Textiles").one()
    # A payment the owner has not confirmed must not enter the memory.
    unconfirmed = Payment(tenant_id=TENANT, party_id=party.id, amount=80000,
                          received_on=TODAY, mode="cash",
                          attributes={"pending_fields": ["amount"]})
    db.add(unconfirmed)
    db.flush()
    brief = refresh_party(db, TENANT, party.id)
    check("an unconfirmed payment does not clear the balance",
          brief["payment_behaviour"]["outstanding"], 80000.0)
    check("  nor become a preferred mode",
          [m["mode"] for m in brief["payment_behaviour"]["modes"]], ["neft"])

print("\n-- incremental --")

with tenant_session(TENANT) as db:
    party = db.query(Party).filter_by(name="Ashok Textiles").one()
    first = (party.attributes or {}).get("brief")
    watermark = first["watermark"]

    order = Order(tenant_id=TENANT, party_id=party.id, order_no="O-NEW",
                  status="confirmed", order_date=TODAY)
    db.add(order)
    db.flush()
    quality = db.query(Item).filter_by(code="SR-1042").one()
    db.add(OrderLine(tenant_id=TENANT, order_id=order.id, item_id=quality.id,
                     quantity=200, unit="meter", rate=66))
    db.flush()

    second = refresh_party(db, TENANT, party.id)
    check("the watermark moved", second["watermark"] != watermark, True)
    check("the new order is counted without re-reading history",
          second["buys"][0]["times"], 4)
    check("  and the rate band grew by one observation",
          second["rate_band"]["observations"], 5)

print("\n-- the brief feeds the system back --")

context = as_prompt_context(brief)
check("prompt context mentions what they buy", "SR-1042" in context, True)
check("  and their usual rate", "63" in context, True)
check("an empty brief yields no context", as_prompt_context({}), "")

facts = reminder_facts(brief)
check("reminder facts carry the balance", facts["outstanding"], 80000.0)
check("  and how they usually pay", facts["preferred_mode"], "neft")

with tenant_session(TENANT) as db:
    from app.services.validation import check_rate_band

    party = db.query(Party).filter_by(name="Ashok Textiles").one()
    inside = check_rate_band(db, TENANT, party.id, {"rate": 64})
    check("validation uses the brief's band", inside.status, "pass")
    outside = check_rate_band(db, TENANT, party.id, {"rate": 500})
    check("  and catches an outlier", outside.status, "fail")

print("\n-- refresh_stale --")

with tenant_session(TENANT) as db:
    count = refresh_stale(db, TENANT, older_than_minutes=0)
    check("every party gets a brief", count, 2)
    quiet = db.query(Party).filter_by(name="Quiet Trader").one()
    check("  including one with no history",
          (quiet.attributes or {}).get("brief", {}).get("version") is not None, True)

# --- the API --------------------------------------------------------------

print("\n-- parties api --")

from app.main import app  # noqa: E402

client = TestClient(app)
headers = {"Authorization": f"Bearer {TOKEN}"}

listing = client.get("/api/parties", headers=headers).json()
check("both parties listed", listing["total"], 2)
check("worst debt first", listing["parties"][0]["name"], "Ashok Textiles")
check("outstanding on the row", listing["parties"][0]["outstanding"], 80000.0)
check("total outstanding", listing["total_outstanding"], 80000.0)

check("search by name",
      client.get("/api/parties?q=quiet", headers=headers).json()["total"], 1)
check("overdue filter",
      client.get("/api/parties?overdue_only=true", headers=headers).json()["total"], 1)

with tenant_session(TENANT) as db:
    party_id = db.query(Party).filter_by(name="Ashok Textiles").one().id

detail = client.get(f"/api/parties/{party_id}", headers=headers).json()
check("detail carries the brief", detail["brief"]["buys"][0]["quality"], "SR-1042")
check("  the ledger it is derived from", len(detail["entries"]) > 0, True)
check("  the order history", len(detail["orders"]), 5)
check("  and a drafted reminder", detail["reminder_link"].startswith("https://wa.me/"), True)
check("the reminder mentions the balance", "80%2C000" in detail["reminder_link"], True)
check("internal accumulators are not exposed",
      any(k.startswith("_") for k in detail["brief"]), False)
check("a missing party 404s",
      client.get(f"/api/parties/{uuid.uuid4()}", headers=headers).status_code, 404)

print("\n-- orders api --")

page = client.get("/api/orders", headers=headers).json()
check("orders listed", page["total"], 5)
check("counts by status", page["by_status"]["confirmed"], 5)
check("filter by status",
      client.get("/api/orders?status=draft", headers=headers).json()["total"], 0)
check("filter by party",
      client.get(f"/api/orders?party_id={party_id}", headers=headers).json()["total"], 5)

order_id = page["orders"][0]["id"]
order = client.get(f"/api/orders/{order_id}", headers=headers).json()
check("detail carries lines", len(order["lines"]) >= 1, True)
check("  the party", order["party_name"], "Ashok Textiles")
check("  and a computed value", order["value"] > 0, True)
check("a missing order 404s",
      client.get(f"/api/orders/{uuid.uuid4()}", headers=headers).status_code, 404)

check("parties needs a token", client.get("/api/parties").status_code, 401)
check("orders needs a token", client.get("/api/orders").status_code, 401)

print("\n-- isolation --")

OTHER = uuid.uuid4()
with admin_session() as db:
    other = Tenant(id=OTHER, business_name="Other",
                   owner_phone=f"97{uuid.uuid4().int % 10**8:08d}")
    OTHER_TOKEN = issue_token(other)
    db.add(other)
with tenant_session(OTHER) as db:
    db.add(BusinessProfile(tenant_id=OTHER, segments=[], modules={}, vocabulary={},
                           rules={}, examples=[]))

other_headers = {"Authorization": f"Bearer {OTHER_TOKEN}"}
check("another tenant sees no parties",
      client.get("/api/parties", headers=other_headers).json()["total"], 0)
check("  and cannot open ours",
      client.get(f"/api/parties/{party_id}", headers=other_headers).status_code, 404)
check("  nor our orders",
      client.get(f"/api/orders/{order_id}", headers=other_headers).status_code, 404)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
