"""Verification for the two mistakes this codebase keeps repeating.

Neither of these is a feature. Both are bug classes that have shipped silent
wrong answers, and both are the kind that a passing test suite happily steps
over — the query returns nothing, or the count is zero, and nothing raises.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_foundations.py
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from app.db import admin_session, tenant_session
from app.models import Dispatch, Order, Party, Tenant
from app.services.clock import (
    IST_OFFSET,
    business_day_bounds,
    business_now,
    business_today,
)
from app.services.sql import not_in_subquery, not_in_values

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


TENANT = uuid.uuid4()
with admin_session() as db:
    db.add(Tenant(id=TENANT, business_name="Foundation Mills",
                  owner_phone=f"98{uuid.uuid4().int % 10**8:08d}"))
with tenant_session(TENANT) as db:
    party = Party(tenant_id=TENANT, name="Someone", phone="9000000001")
    db.add(party)
    db.flush()
    db.add(Order(tenant_id=TENANT, party_id=party.id, order_no="A", status="draft"))
    db.add(Order(tenant_id=TENANT, party_id=party.id, order_no="B", status="draft"))
    db.add(Order(tenant_id=TENANT, party_id=party.id, order_no="C", status="closed"))

# The column default fills in "draft", so the NULL has to be written directly.
# That is also how one arrives in real data: an import, or a partial commit
# that never set a status.
with tenant_session(TENANT) as db:
    db.execute(
        text('UPDATE "order" SET status = NULL '
             "WHERE order_no = 'B' AND tenant_id = :t"),
        {"t": str(TENANT)},
    )

print("\n-- NOT IN cannot be poisoned by a NULL --")

with tenant_session(TENANT) as db:
    sub = select(Dispatch.order_id).where(Dispatch.tenant_id == TENANT)
    before = db.execute(
        select(Order).where(Order.tenant_id == TENANT, not_in_subquery(Order.id, sub))
    ).scalars().all()
check("with no dispatches, every order is 'not dispatched'", len(before), 3)

with tenant_session(TENANT) as db:
    # The poison: one dispatch row with no order attached.
    db.add(Dispatch(tenant_id=TENANT, order_id=None))

with tenant_session(TENANT) as db:
    sub = select(Dispatch.order_id).where(Dispatch.tenant_id == TENANT)
    after = db.execute(
        select(Order).where(Order.tenant_id == TENANT, not_in_subquery(Order.id, sub))
    ).scalars().all()
check("A NULL IN THE SUBQUERY DOES NOT BLANK THE RESULT", len(after), 3)

with tenant_session(TENANT) as db:
    # And the naive form, to prove the trap is real rather than theoretical.
    naive = db.execute(
        select(Order).where(
            Order.tenant_id == TENANT,
            Order.id.notin_(select(Dispatch.order_id).where(
                Dispatch.tenant_id == TENANT)),
        )
    ).scalars().all()
check("  (the naive form really does return nothing)", len(naive), 0)

with tenant_session(TENANT) as db:
    real = db.execute(select(Order).where(Order.tenant_id == TENANT)).scalars().first()
    db.add(Dispatch(tenant_id=TENANT, order_id=real.id))

with tenant_session(TENANT) as db:
    sub = select(Dispatch.order_id).where(Dispatch.tenant_id == TENANT)
    left = db.execute(
        select(Order).where(Order.tenant_id == TENANT, not_in_subquery(Order.id, sub))
    ).scalars().all()
check("a genuinely dispatched order is excluded", len(left), 2)

print("\n-- NOT IN on a column keeps NULLs --")

with tenant_session(TENANT) as db:
    open_orders = db.execute(
        select(Order).where(
            Order.tenant_id == TENANT,
            not_in_values(Order.status, ["closed", "cancelled"]),
        )
    ).scalars().all()
statuses = sorted((o.status or "NULL") for o in open_orders)
check("a NULL status is not treated as closed", statuses, ["NULL", "draft"])

print("\n-- one definition of today --")

check("business_today is IST, not the server's date",
      business_today(), (datetime.utcnow() + IST_OFFSET).date())
check("  and business_now agrees with it", business_now().date(), business_today())

start, end = business_day_bounds()
check("the day is exactly 24 hours", end - start, timedelta(days=1))
check("  it starts at 18:30 UTC the day before", (start.hour, start.minute), (18, 30))
check("  and now falls inside it", start <= datetime.utcnow() < end, True)

# The bug that shipped: a row written at 01:00 IST is dated the previous day
# in UTC, so a func.date() comparison against the local date missed it.
one_am_ist = datetime.combine(business_today(), datetime.min.time()) + timedelta(hours=1)
as_utc = one_am_ist - IST_OFFSET
check("A ROW WRITTEN AT 1AM IST FALLS IN TODAY", start <= as_utc < end, True)
check("  even though its UTC date is yesterday", as_utc.date() != business_today(), True)

print("\n-- nobody reintroduces them --")

app_files = [p for p in Path("app").rglob("*.py")]

offenders = []
for path in app_files:
    if path.name in {"clock.py", "sql.py"}:
        continue
    source = path.read_text(encoding="utf-8")
    # Comments may name it while explaining why it is not used.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    if re.search(r"\bdate\.today\(\)", code):
        offenders.append(str(path))
check("no server-local date.today() anywhere in app/", offenders, [])

raw_notin = []
for path in app_files:
    if path.name == "sql.py":
        continue
    source = path.read_text(encoding="utf-8")
    for line in source.splitlines():
        if ".notin_(" in line and "not_in_" not in line:
            raw_notin.append(f"{path}: {line.strip()[:60]}")
check("no raw .notin_ outside the helper", raw_notin, [])

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
