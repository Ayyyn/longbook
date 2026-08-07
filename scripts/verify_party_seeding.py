"""Verification for party seeding at onboarding.

The headline number this file exists to protect: after onboarding, what share
of a 90-day backfill auto-commits instead of landing in the review queue.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_party_seeding.py
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

import app.agents.configurator as configurator_module
import app.agents.extractor as extractor_module
from app.config import settings
from app.db import tenant_session
from app.models import Invoice, Order, Party, Payment
from app.services.party_import import (
    parse_party_excel,
    parse_tally_xml,
    seeds_from_messages,
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


TALLY_XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<ENVELOPE>
 <BODY><IMPORTDATA><REQUESTDATA>
  <TALLYMESSAGE>
   <LEDGER NAME="Ashok Textiles">
    <PARENT>Sundry Debtors</PARENT>
    <OPENINGBALANCE>-125000.00</OPENINGBALANCE>
    <LEDGERMOBILE>9876543210</LEDGERMOBILE>
    <PARTYGSTIN>24ABCDE1234F1Z5</PARTYGSTIN>
    <BILLCREDITPERIOD>45 Days</BILLCREDITPERIOD>
    <MAILINGNAME>Ashok Tex</MAILINGNAME>
   </LEDGER>
   <LEDGER NAME="Bharat Fabrics">
    <PARENT>Sundry Debtors</PARENT>
    <OPENINGBALANCE>-48000.00</OPENINGBALANCE>
    <LEDGERPHONE>0261-2234567</LEDGERPHONE>
   </LEDGER>
   <LEDGER NAME="Kishore Silk Mills">
    <PARENT>Sundry Creditors</PARENT>
    <OPENINGBALANCE>75000.00</OPENINGBALANCE>
   </LEDGER>
   <LEDGER NAME="HDFC Bank Current A/c">
    <PARENT>Bank Accounts</PARENT>
    <OPENINGBALANCE>500000.00</OPENINGBALANCE>
   </LEDGER>
   <LEDGER NAME="Rent Paid">
    <PARENT>Indirect Expenses</PARENT>
   </LEDGER>
  </TALLYMESSAGE>
 </REQUESTDATA></IMPORTDATA></BODY>
</ENVELOPE>
"""

print("\n-- tally xml --")

seeds = parse_tally_xml(TALLY_XML)
by_name = {s.name: s for s in seeds}
check("only parties imported, not banks or expenses", sorted(by_name),
      ["Ashok Textiles", "Bharat Fabrics", "Kishore Silk Mills"])
check("debtors are customers", by_name["Ashok Textiles"].kind, "customer")
check("creditors are suppliers", by_name["Kishore Silk Mills"].kind, "supplier")
check("negative opening balance read as an amount owed",
      by_name["Ashok Textiles"].outstanding, 125000.0)
check("mobile preferred over landline", by_name["Ashok Textiles"].phone, "9876543210")
check("landline still captured", by_name["Bharat Fabrics"].phone, "0261-2234567")
check("gstin captured", by_name["Ashok Textiles"].gstin, "24ABCDE1234F1Z5")
check("credit period parsed from '45 Days'", by_name["Ashok Textiles"].credit_days, 45)
check("mailing name becomes an alias", by_name["Ashok Textiles"].aliases, ["Ashok Tex"])
check("latin-1 bytes are readable", len(parse_tally_xml(TALLY_XML.encode("iso-8859-1"))), 3)

try:
    parse_tally_xml("<not xml")
    check("garbage is rejected", "no error", "ValueError")
except ValueError:
    check("garbage is rejected", "ValueError", "ValueError")

print("\n-- excel party list --")


def build_sheet(rows, headers):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    path = Path(f"var/test-{uuid.uuid4().hex[:8]}.xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return path


sheet_path = build_sheet(
    [
        ["Ashok Textiles", "98765 43210", "Surat", 45, 125000],
        ["Naya Trader", "9000011111", "Mumbai", None, None],
        [None, "ignored", "", None, None],
    ],
    ["Party Name", "Mobile No", "City", "Credit Days", "Outstanding"],
)
excel_seeds = parse_party_excel(sheet_path)
check("rows read", [s.name for s in excel_seeds], ["Ashok Textiles", "Naya Trader"])
check("columns matched regardless of wording", excel_seeds[0].city, "Surat")
check("outstanding read", excel_seeds[0].outstanding, 125000.0)
check("blank names skipped", len(excel_seeds), 2)

bad_path = build_sheet([["x"]], ["Something Else"])
try:
    parse_party_excel(bad_path)
    check("a sheet with no name column is rejected", "no error", "ValueError")
except ValueError:
    check("a sheet with no name column is rejected", "ValueError", "ValueError")

# --- the end-to-end number ------------------------------------------------


def fake_configurator(*, model, system, user, **kwargs):
    return (
        {"segments": ["wholesaler"], "modules": {}, "vocabulary": {}, "rules": {},
         "confidence": 0.9, "reason": "sample"},
        {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
    )


def fake_extractor(*, model, system, user, **kwargs):
    """Realistic shape: trade messages in a 1:1 chat name nobody."""
    body = (user or "").lower()
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    if "rtgs" in body or "payment" in body:
        return {"record_type": "payment", "confidence": 0.94, "reason": "",
                "fields": {"amount": "50000", "mode": "neft"}}, usage
    if "mtr" in body or "meter" in body:
        return {"record_type": "order", "confidence": 0.93, "reason": "",
                "fields": {"quality": "SR-1042", "quantity": "150",
                           "unit": "meter", "rate": "62"}}, usage
    if "lr no" in body:
        return {"record_type": "dispatch", "confidence": 0.92, "reason": "",
                "fields": {"lr_no": "448821", "transporter": "VRL"}}, usage
    return {"record_type": "noise", "confidence": 1.0, "reason": "", "fields": {}}, usage


configurator_module.generate_json = fake_configurator
extractor_module.generate_json = fake_extractor

from app.main import app  # noqa: E402

client = TestClient(app)
settings().admin_token = "admin"
admin = {"X-Admin-Token": "admin"}

# A 1:1 chat names the sender by contact name; a group names them by number.
SENDERS = ["Ashok Textiles", "Bharat Fabrics", "+91 90000 11111"]
BODIES = [
    "150 mtr SR-1042 chahiye rate 62 nett",
    "aaj 50000 rtgs kar diya",
    "Good morning ji",
    "LR no 448821 se bhej diya, transporter VRL",
    "300 meter bhej dena",
]


def build_export(days: int = 6) -> bytes:
    lines = []
    for day in range(1, days + 1):
        for index, sender in enumerate(SENDERS):
            body = BODIES[(day + index) % len(BODIES)]
            lines.append(f"[{day:02d}/06/26, 1{index}:0{day % 6}:00 AM] {sender}: {body}")
    return "\n".join(lines).encode()


def onboard(business: str, party_file: tuple | None):
    created = client.post("/api/tenants", headers=admin, json={
        "business_name": business, "owner_phone": f"9{uuid.uuid4().int % 10**9:09d}",
    }).json()
    headers = {"Authorization": f"Bearer {created['token']}"}
    client.post("/api/tenants/sample", headers=headers,
                files={"file": ("chat.txt", build_export(), "text/plain")})
    imported = None
    if party_file:
        imported = client.post("/api/tenants/parties", headers=headers,
                               files={"file": party_file}).json()
    configured = client.post("/api/tenants/configure", headers=headers,
                             json={"segments": ["wholesaler"]}).json()
    return uuid.UUID(created["tenant_id"]), headers, imported, configured


def rates(tenant_id, headers):
    queue = client.get("/api/review/queue?limit=200", headers=headers).json()
    with tenant_session(tenant_id) as db:
        committed = db.query(Order).count() + db.query(Payment).count()
    business = committed + queue["total"]
    return committed, queue["total"], (committed / business if business else 0)


print("\n-- backfill with parties seeded from the chat --")

tenant_a, headers_a, _, configured_a = onboard("Chat Seeded", None)
check("seeded from messages", configured_a["parties_seeded_from"], "messages")
check("one party per counterparty", configured_a["parties"], 3)

with tenant_session(tenant_a) as db:
    names = sorted(p.name for p in db.query(Party).all())
    check("parties are the senders", names, ["+91 90000 11111", "Ashok Textiles", "Bharat Fabrics"])
    numbered = db.query(Party).filter(Party.name == "+91 90000 11111").one()
    check("a numeric sender keeps its phone", numbered.phone, "9000011111")

committed_a, queued_a, rate_a = rates(tenant_a, headers_a)
print(f"        auto-committed {committed_a}, queued {queued_a} = {rate_a:.0%}")
check("the majority auto-commits", rate_a > 0.5, True)
check("  and the queue is short", queued_a <= committed_a, True)

print("\n-- backfill with parties imported from Tally --")

tally_file = ("ledgers.xml", TALLY_XML.encode("iso-8859-1"), "application/xml")
tenant_b, headers_b, imported_b, configured_b = onboard("Tally Seeded", tally_file)

check("tally import reported", imported_b["source"], "tally")
check("three parties created", imported_b["created"], 3)
check("opening balances became invoices", imported_b["opening_invoices"], 3)
check("outstanding totalled", imported_b["total_outstanding"], 248000.0)
check("chat tops up the imported list", configured_b["parties_seeded_from"],
      "messages (topped up import)")
check("  with only the sender Tally never knew about", configured_b["parties"], 4)

with tenant_session(tenant_b) as db:
    check("tally names were not duplicated",
          db.query(Party).filter_by(name="Ashok Textiles").count(), 1)
    check("opening invoices are open", db.query(Invoice).filter_by(status="open").count(), 3)
    ashok = db.query(Party).filter_by(name="Ashok Textiles").one()
    check("credit terms carried over", ashok.credit_days, 45)
    check("alias carried over", "Ashok Tex" in (ashok.aliases or []), True)

committed_b, queued_b, rate_b = rates(tenant_b, headers_b)
print(f"        auto-committed {committed_b}, queued {queued_b} = {rate_b:.0%}")
check("the majority auto-commits", rate_b > 0.5, True)

print("\n-- import is idempotent --")

again = client.post("/api/tenants/parties", headers=headers_b,
                    files={"file": tally_file}).json()
check("re-import creates nothing", again["created"], 0)
check("  it merges instead", again["merged"], 3)
check("  and does not double the outstanding", again["opening_invoices"], 0)
with tenant_session(tenant_b) as db:
    check("still four parties", db.query(Party).count(), 4)
    check("still three opening invoices", db.query(Invoice).count(), 3)

print("\n-- seeds_from_messages excludes the owner --")

with tenant_session(tenant_a) as db:
    derived = seeds_from_messages(db, tenant_a, owner_phone="+91 90000 11111")
    check("the owner's own number is not a party",
          sorted(s.name for s in derived), ["Ashok Textiles", "Bharat Fabrics"])

for path in Path("var").glob("test-*.xlsx"):
    path.unlink(missing_ok=True)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
