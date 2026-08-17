"""Verification for the analytics layer.

Two properties, and the second is the one that matters.

1. Every figure is computed by the database. A dashboard number carries no
   citation and no visible workings, so if a model ever produces one there is
   nothing for anybody to catch it with.
2. Absence is reported rather than filled. No margin without cost data, no
   comparison without history, no percentage growth from zero. A dashboard
   that quietly invents is worse than one that admits a gap, because
   afterwards nobody can tell which figures to trust.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_analytics.py
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Invoice, Order, OrderLine, Party, Payment, Tenant
from app.services import analytics
from app.services.auth import issue_token

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


def make(name: str) -> uuid.UUID:
    tid = uuid.uuid4()
    with admin_session() as db:
        t = Tenant(id=tid, business_name=name,
                   owner_phone=f"93{uuid.uuid4().int % 10**8:08d}",
                   onboarded_at=datetime.utcnow(),
                   paid_until=datetime.utcnow() + timedelta(days=90))
        issue_token(t)
        db.add(t)
    with tenant_session(tid) as db:
        db.add(BusinessProfile(tenant_id=tid, segments=["wholesaler"], modules={},
                               vocabulary={}, rules={}, examples=[]))
    return tid


# --------------------------------------------------------------------------
print("\n-- a business with nothing in it --")

EMPTY = make("Empty Traders")
with tenant_session(EMPTY) as db:
    sc = analytics.discover(db, "Empty Traders")
check("no records is reported as zero", sc.records, 0)
check("  and no measure claims to be available",
      [m.key for m in sc.measures if m.available], [])
check("  every unavailable measure says why",
      all(m.why_not for m in sc.measures if not m.available), True)
check("  the date range is empty rather than invented",
      (sc.first_record, sc.last_record), (None, None))


# --------------------------------------------------------------------------
print("\n-- a business with a real book --")

FULL = make("Rajkot Hardware")
with tenant_session(FULL) as db:
    a = Party(tenant_id=FULL, name="Mehta Traders", kind="customer",
              city="Rajkot", phone="9876500001")
    b = Party(tenant_id=FULL, name="Shah Industrial", kind="customer",
              city="Morbi", phone="9876500002")
    s = Party(tenant_id=FULL, name="Bearing Depot", kind="supplier",
              city="Rajkot", phone="9876500003")
    db.add_all([a, b, s])
    db.flush()

    # Payments across two months, so a monthly series has more than one point.
    db.add(Payment(tenant_id=FULL, party_id=a.id, amount=120000, mode="neft",
                   received_on=TODAY - timedelta(days=40)))
    db.add(Payment(tenant_id=FULL, party_id=a.id, amount=80000, mode="upi",
                   received_on=TODAY - timedelta(days=5)))
    db.add(Payment(tenant_id=FULL, party_id=b.id, amount=45000, mode="cheque",
                   received_on=TODAY - timedelta(days=3)))

    for party, no, days in [(a, "ORD-1", 20), (b, "ORD-2", 10), (a, "ORD-3", 2)]:
        o = Order(tenant_id=FULL, party_id=party.id, order_no=no,
                  order_date=TODAY - timedelta(days=days), status="open")
        db.add(o)
        db.flush()
        db.add(OrderLine(tenant_id=FULL, order_id=o.id,
                         raw_description="6205 ZZ bearing", quantity=200, unit="nos"))

    db.add(Invoice(tenant_id=FULL, party_id=a.id, invoice_no="INV-1", amount=95000,
                   invoice_date=TODAY - timedelta(days=80),
                   due_date=TODAY - timedelta(days=35), status="open"))

with tenant_session(FULL) as db:
    sc = analytics.discover(db, "Rajkot Hardware")

check("received is available", any(m.key == "received" and m.available for m in sc.measures), True)
check("orders is available", any(m.key == "orders" and m.available for m in sc.measures), True)
check("party and city are dimensions",
      {d.key for d in sc.dimensions if d.available} >= {"party", "city", "party_kind"}, True)

# The point of the whole exercise: a measure with no data behind it is named
# and explained, never quietly produced.
margin = next(m for m in sc.measures if m.key == "margin")
check("margin is NOT available", margin.available, False)
check("  and says exactly why", "cost" in margin.why_not.lower(), True)


print("\n-- the figures come from SQL, and they are right --")

with tenant_session(FULL) as db:
    got = analytics.total(db, "received", TODAY - timedelta(days=89), TODAY)
check("received sums the payments", got, 245000.0)

with tenant_session(FULL) as db:
    week = analytics.total(db, "received", TODAY - timedelta(days=6), TODAY)
check("  and respects the window", week, 125000.0)

with tenant_session(FULL) as db:
    rows = analytics.breakdown(db, "received", "party",
                               TODAY - timedelta(days=89), TODAY)
check("breakdown by party is largest first",
      [r["label"] for r in rows], ["Mehta Traders", "Shah Industrial"])
check("  with the right totals", [r["value"] for r in rows], [200000.0, 45000.0])

with tenant_session(FULL) as db:
    by_city = analytics.breakdown(db, "orders", "city",
                                  TODAY - timedelta(days=89), TODAY)
check("orders split by city", sorted((r["label"], r["value"]) for r in by_city),
      [("Morbi", 1.0), ("Rajkot", 2.0)])

with tenant_session(FULL) as db:
    filtered = analytics.total(db, "received", TODAY - timedelta(days=89), TODAY,
                               {"party_kind": "customer"})
check("a filter narrows the figure", filtered, 245000.0)
with tenant_session(FULL) as db:
    suppliers = analytics.total(db, "received", TODAY - timedelta(days=89), TODAY,
                                {"party_kind": "supplier"})
check("  and a filter with nothing behind it returns zero, not everything",
      suppliers, 0.0)


print("\n-- a relationship that does not exist is refused --")

with tenant_session(FULL) as db:
    try:
        analytics.breakdown(db, "received", "item",
                            TODAY - timedelta(days=89), TODAY)
        refused = False
    except analytics.AnalyticsError as exc:
        refused = "not related" in str(exc)
check("payments cannot be split by item", refused, True)

with tenant_session(FULL) as db:
    try:
        analytics.breakdown(db, "received", "secret_column",
                            TODAY - timedelta(days=89), TODAY)
        rejected = False
    except analytics.AnalyticsError:
        rejected = True
check("an invented dimension is rejected, never interpolated", rejected, True)

with tenant_session(FULL) as db:
    try:
        analytics.total(db, "profit", TODAY - timedelta(days=89), TODAY)
        rejected_m = False
    except analytics.AnalyticsError:
        rejected_m = True
check("an invented measure is rejected", rejected_m, True)


print("\n-- comparisons are withheld rather than faked --")

SHORT = make("Two Days Old")
with tenant_session(SHORT) as db:
    p = Party(tenant_id=SHORT, name="New Customer", kind="customer")
    db.add(p)
    db.flush()
    db.add(Payment(tenant_id=SHORT, party_id=p.id, amount=5000, mode="cash",
                   received_on=TODAY))

with tenant_session(SHORT) as db:
    sc_short = analytics.discover(db, "Two Days Old")
    rows = analytics.kpis(db, sc_short, "30d")
received = next(r for r in rows if r["key"] == "received")
check("a business with one day of history gets no percentage",
      received["change_pct"], None)
check("  and is told why", "history" in received["no_comparison"].lower(), True)

# Growth from nothing is not a percentage — printing one would be inventing.
check("growth from an empty previous period is not expressed as a percentage",
      all(r["change_pct"] is None or r["previous"] for r in rows), True)


print("\n-- tenant isolation --")

with tenant_session(EMPTY) as db:
    other = analytics.total(db, "received", TODAY - timedelta(days=365), TODAY)
check("one business cannot see another's money through analytics", other, 0.0)
with tenant_session(EMPTY) as db:
    rows = analytics.breakdown(db, "received", "party",
                               TODAY - timedelta(days=365), TODAY)
check("  nor another's parties", rows, [])


print("\n-- alerts point at something real --")

with tenant_session(FULL) as db:
    sc = analytics.discover(db, "Rajkot Hardware")
    found = analytics.alerts(db, sc)
kinds = {a["kind"] for a in found}
check("the overdue invoice is caught", "overdue" in kinds, True)
check("the stale order is caught", "undispatched" in kinds, True)
check("every alert carries something to open",
      all(a.get("party_id") or a.get("order_id") for a in found), True)
check("every alert has a headline and a detail",
      all(a["headline"] and a["detail"] for a in found), True)


print("\n-- the model is never asked for a number --")

import inspect  # noqa: E402

from app.api import analytics as api_module  # noqa: E402

engine_src = inspect.getsource(analytics)
check("the metrics engine makes no model call",
      "generate_json" in engine_src or "generate_with_tools" in engine_src, False)

# The one endpoint that does call a model must not be one that returns figures.
for name in ("overview", "series", "breakdown", "drill"):
    src = inspect.getsource(getattr(api_module, name))
    check(f"/{name} makes no model call",
          "generate_json" in src or "generate_with_tools" in src, False)

insight_src = inspect.getsource(api_module.insights)
check("insights forbids inventing a number",
      "Never state a number that is not in the data" in insight_src, True)
check("  and forbids asserting a cause",
      "Never assert a cause" in insight_src, True)


print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
