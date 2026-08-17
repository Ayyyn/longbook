"""Verification for owner sign-in.

Sign-in is phone + token with no server session: the token is the tenant, and
the phone is checked against the tenant it belongs to. That check is the only
thing standing between a pasted token and someone else's books, so it is
tested here rather than trusted to the browser.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_login.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.db import admin_session
from app.models import Tenant
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


PHONE = f"98{uuid.uuid4().int % 10**8:08d}"
TENANT = uuid.uuid4()
with admin_session() as db:
    tenant = Tenant(id=TENANT, business_name="Login Mills", owner_phone=f"+91{PHONE}",
                    onboarded_at=datetime.utcnow(), paid_until=datetime.utcnow() + timedelta(days=365))
    TOKEN = issue_token(tenant)
    db.add(tenant)

OTHER = uuid.uuid4()
with admin_session() as db:
    other = Tenant(id=OTHER, business_name="Other Mills",
                   owner_phone=f"97{uuid.uuid4().int % 10**8:08d}", paid_until=datetime.utcnow() + timedelta(days=365))
    OTHER_TOKEN = issue_token(other)
    db.add(other)

from app.main import app  # noqa: E402

client = TestClient(app)

print("\n-- what the login screen calls --")

live_headers = {"Authorization": f"Bearer {TOKEN}"}
resp = client.get("/api/tenants/me", headers=live_headers)
check("a good token identifies the tenant", resp.status_code, 200)
# Stored digits-only by the model validator, so that is what comes back.
check("  and returns the phone to check against", resp.json()["owner_phone"], f"91{PHONE}")
check("  and the business name to show", resp.json()["business_name"], "Login Mills")

check("no token is a 401", client.get("/api/tenants/me").status_code, 401)
check("a junk token is a 401",
      client.get("/api/tenants/me", headers={"Authorization": "Bearer tex_nonsense"}).status_code,
      401)
check("a well-formed token for a dead tenant is a 401",
      client.get("/api/tenants/me",
                 headers={"Authorization": f"Bearer {issue_token(Tenant(id=uuid.uuid4(), business_name='Ghost', owner_phone='+910000000000', paid_until=datetime.utcnow() + timedelta(days=365)))}"}).status_code,
      401)

print("\n-- the phone check is what stops token reuse --")


def digits(value: str) -> str:
    return "".join(c for c in (value or "") if c.isdigit())[-10:]


def same_phone(a: str, b: str) -> bool:
    """Mirror of samePhone() in frontend/app/lib/api.js."""
    left = digits(a)
    return len(left) == 10 and left == digits(b)


me = client.get("/api/tenants/me", headers={"Authorization": f"Bearer {TOKEN}"}).json()
check("the owner's own number matches", same_phone(PHONE, me["owner_phone"]), True)
check("  spaced", same_phone(f"{PHONE[:5]} {PHONE[5:]}", me["owner_phone"]), True)
check("  with country code", same_phone(f"+91 {PHONE}", me["owner_phone"]), True)
check("  with a leading zero", same_phone(f"0{PHONE}", me["owner_phone"]), True)

other_me = client.get("/api/tenants/me",
                      headers={"Authorization": f"Bearer {OTHER_TOKEN}"}).json()
check("another business's token does not match this phone",
      same_phone(PHONE, other_me["owner_phone"]), False)
check("  and that token reaches only its own tenant",
      other_me["business_name"], "Other Mills")
check("an empty phone never matches", same_phone("", me["owner_phone"]), False)
check("a short number never matches", same_phone("12345", me["owner_phone"]), False)

print("\n-- every screen's data needs the token --")

for path in ["/api/today", "/api/review/queue", "/api/parties", "/api/orders",
             "/api/agents/summary"]:
    check(f"{path} is 401 without a token", client.get(path).status_code, 401)

print("\n-- losing a token, and getting back in --")

from app.config import settings  # noqa: E402

admin = {"X-Admin-Token": settings().admin_token}
if not settings().admin_token:
    print("  SKIP  admin token unset in this environment")
else:
    # The support call starts with a phone number, not a uuid.
    found = client.get(f"/api/tenants/lookup?phone={PHONE}", headers=admin)
    check("lookup by phone finds the business", found.status_code, 200)
    check("  and returns exactly one", len(found.json()), 1)
    check("  named correctly", found.json()[0]["business_name"], "Login Mills")
    check("  with its access state, for the person on the call",
          found.json()[0]["access_status"] in {"trial", "active", "expired"}, True)
    check("  the last ten digits are enough",
          len(client.get(f"/api/tenants/lookup?phone={PHONE[-10:]}", headers=admin).json()), 1)
    check("lookup needs the admin token",
          client.get(f"/api/tenants/lookup?phone={PHONE}").status_code, 401)
    check("a number nobody has returns nothing",
          client.get("/api/tenants/lookup?phone=0000000000", headers=admin).json(), [])

    # Re-issue is the only recovery: the stored digest cannot be reversed.
    issued = client.post(f"/api/tenants/{TENANT}/token?email=false", headers=admin)
    check("a fresh token can be issued", issued.status_code, 200)
    new_token = issued.json()["token"]
    check("  and it is not the old one", new_token != TOKEN, True)
    check("  the new one works",
          client.get("/api/tenants/me",
                     headers={"Authorization": f"Bearer {new_token}"}).status_code, 200)
    check("  and the old one stops working immediately",
          client.get("/api/tenants/me", headers=live_headers).status_code, 401)
    check("re-issue needs the admin token",
          client.post(f"/api/tenants/{TENANT}/token").status_code, 401)
    check("re-issuing for a missing tenant 404s",
          client.post(f"/api/tenants/{uuid.uuid4()}/token", headers=admin).status_code, 404)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
