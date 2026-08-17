"""Verification for tenant access states.

Payment is recorded by hand, so the only thing standing between a lapsed
tenant and the app is `paid_until` and the guard that reads it. The rule that
matters most is the one about data: an expired tenant is locked out, never
emptied.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_access.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Party, Tenant
from app.services.access import access_for
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


def make_tenant(**kwargs) -> tuple[uuid.UUID, str]:
    tid = uuid.uuid4()
    with admin_session() as db:
        tenant = Tenant(
            id=tid,
            business_name=kwargs.pop("name", "Access Mills"),
            owner_phone=f"98{uuid.uuid4().int % 10**8:08d}",
            onboarded_at=datetime.utcnow(),
            **kwargs,
        )
        token = issue_token(tenant)
        db.add(tenant)
    with tenant_session(tid) as db:
        db.add(BusinessProfile(tenant_id=tid, segments=["wholesaler"], modules={},
                               vocabulary={}, rules={}, examples=[]))
        db.add(Party(tenant_id=tid, name="Ashok Textiles", phone="9876543210"))
    return tid, token


print("\n-- the states --")

now = datetime.utcnow()

# There is no free trial. Access is something somebody granted, or it does
# not exist — a business that has never been paid for is expired on day one,
# not on day fifteen.
fresh = Tenant(business_name="x", owner_phone="1", created_at=now, is_active=True)
check("a brand new tenant has no access", access_for(fresh, now).status, "expired")
check("  and is not allowed in", access_for(fresh, now).allowed, False)

old = Tenant(business_name="x", owner_phone="1",
             created_at=now - timedelta(days=30), is_active=True)
check("an old tenant nobody paid for is still expired", access_for(old, now).status, "expired")

paid = Tenant(business_name="x", owner_phone="1", created_at=now - timedelta(days=400),
              paid_until=now + timedelta(days=30), is_active=True)
check("paying makes it active", access_for(paid, now).status, "active")
check("  with days remaining", access_for(paid, now).days_remaining, 30)
check("  and not warned this early", access_for(paid, now).expiring_soon, False)

soon = Tenant(business_name="x", owner_phone="1", created_at=now,
              paid_until=now + timedelta(days=5), is_active=True)
check("near expiry is flagged", access_for(soon, now).expiring_soon, True)

lapsed = Tenant(business_name="x", owner_phone="1", created_at=now - timedelta(days=400),
                paid_until=now - timedelta(days=1), is_active=True)
check("a lapsed subscription is expired", access_for(lapsed, now).status, "expired")

off = Tenant(business_name="x", owner_phone="1", created_at=now,
             paid_until=now + timedelta(days=365), is_active=False)
check("switching a tenant off beats a valid payment", access_for(off, now).status, "expired")

print("\n-- the guard --")

from app.main import app  # noqa: E402

client = TestClient(app)

active_id, active_token = make_tenant(paid_until=datetime.utcnow() + timedelta(days=90))
live = {"Authorization": f"Bearer {active_token}"}
check("an active tenant reaches Today", client.get("/api/today", headers=live).status_code, 200)
check("  and Parties", client.get("/api/parties", headers=live).status_code, 200)

dead_id, dead_token = make_tenant(paid_until=datetime.utcnow() - timedelta(days=2))
gone = {"Authorization": f"Bearer {dead_token}"}
for path in ["/api/today", "/api/parties", "/api/orders", "/api/review/queue",
             "/api/agents/summary", "/api/ingest/jobs/latest"]:
    check(f"expired is locked out of {path}", client.get(path, headers=gone).status_code, 402)

check("  but can still load its own account",
      client.get("/api/tenants/me", headers=gone).status_code, 200)
me = client.get("/api/tenants/me", headers=gone).json()
check("  which reports the status", me["access_status"], "expired")
check("  and names the business, so the screen is not anonymous",
      me["business_name"], "Access Mills")

print("\n-- expiry locks out, it does not delete --")

with tenant_session(dead_id) as db:
    check("the party is still there", db.query(Party).count(), 1)
    check("the profile is still there", db.query(BusinessProfile).count(), 1)

print("\n-- recording a payment --")

check("payment needs the admin token",
      client.post(f"/api/tenants/{dead_id}/payment",
                  json={"paid_until": "2027-01-01T00:00:00"}).status_code,
      401)

from app.config import settings  # noqa: E402

admin = {"X-Admin-Token": settings().admin_token}
if not settings().admin_token:
    print("  SKIP  admin token unset in this environment")
else:
    resp = client.post(
        f"/api/tenants/{dead_id}/payment",
        headers=admin,
        json={"paid_until": (datetime.utcnow() + timedelta(days=365)).isoformat(),
              "plan": "annual_prepaid"},
    )
    check("recording a payment works", resp.status_code, 200)
    check("  and reports the new status", resp.json()["access_status"], "active")
    check("  restoring access immediately",
          client.get("/api/today", headers=gone).status_code, 200)
    check("  with the data intact",
          client.get("/api/parties", headers=gone).json()["total"], 1)
    check("a payment for a missing tenant 404s",
          client.post(f"/api/tenants/{uuid.uuid4()}/payment", headers=admin,
                      json={"paid_until": "2027-01-01T00:00:00"}).status_code,
          404)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
