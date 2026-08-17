"""Verification for self-serve token recovery.

The dangerous version of this feature rotates a token when someone types a
phone number, which lets anyone holding a phone book sign a trader out of
their own books every morning. The whole design rests on one property:
**requesting recovery changes nothing.** That is what is asserted hardest here.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_recovery.py
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.config import settings
from app.db import admin_session
from app.models import Tenant
from app.services import recovery
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
    tenant = Tenant(id=TENANT, business_name="Recovery Mills", owner_phone=f"+91{PHONE}",
                    owner_email="owner@example.invalid", onboarded_at=datetime.utcnow(), paid_until=datetime.utcnow() + timedelta(days=365))
    TOKEN = issue_token(tenant)
    db.add(tenant)

NO_EMAIL_PHONE = f"97{uuid.uuid4().int % 10**8:08d}"
with admin_session() as db:
    db.add(Tenant(business_name="No Email Mills", owner_phone=f"+91{NO_EMAIL_PHONE}", paid_until=datetime.utcnow() + timedelta(days=365)))

from app.main import app  # noqa: E402

client = TestClient(app)
live = {"Authorization": f"Bearer {TOKEN}"}

print("\n-- signing the link --")

if not settings().admin_token:
    print("  SKIP  admin token unset; recovery links cannot be signed")
else:
    payload = recovery.sign(TENANT)
    check("a signed link resolves to its tenant", recovery.verify(payload), TENANT)

    tampered = payload[:-2] + ("aa" if not payload.endswith("aa") else "bb")
    try:
        recovery.verify(tampered)
        check("a tampered signature is rejected", "accepted", "rejected")
    except recovery.RecoveryError:
        check("a tampered signature is rejected", "rejected", "rejected")

    try:
        recovery.verify(recovery.sign(TENANT, issued_at=int(time.time()) - recovery.TTL_SECONDS - 60))
        check("an expired link is rejected", "accepted", "rejected")
    except recovery.RecoveryError:
        check("an expired link is rejected", "rejected", "rejected")

    try:
        recovery.verify("not-a-link")
        check("nonsense is rejected", "accepted", "rejected")
    except recovery.RecoveryError:
        check("nonsense is rejected", "rejected", "rejected")

    # A link signed for one tenant must never open another's account.
    other = recovery.sign(uuid.uuid4())
    check("a link is bound to one tenant", recovery.verify(other) != TENANT, True)

print("\n-- asking for a link changes nothing --")

resp = client.post("/api/tenants/recover", json={"phone": PHONE})
check("the request is accepted", resp.status_code, 200)
check("  THE EXISTING TOKEN STILL WORKS",
      client.get("/api/tenants/me", headers=live).status_code, 200)

for _ in range(3):
    client.post("/api/tenants/recover", json={"phone": PHONE})
check("  and still works after repeated requests",
      client.get("/api/tenants/me", headers=live).status_code, 200)

print("\n-- the response never leaks who is a customer --")

known = client.post("/api/tenants/recover", json={"phone": PHONE}).json()
unknown = client.post("/api/tenants/recover", json={"phone": "9000000000"}).json()
no_email = client.post("/api/tenants/recover", json={"phone": NO_EMAIL_PHONE}).json()
check("a known number and an unknown one answer identically", known, unknown)
check("  as does one with no email on file", known, no_email)
check("a short number is accepted without complaint",
      client.post("/api/tenants/recover", json={"phone": "12"}).status_code, 200)

print("\n-- opening the link is what rotates --")

if settings().admin_token:
    confirmed = client.post("/api/tenants/recover/confirm",
                            json={"token_payload": recovery.sign(TENANT)})
    check("the link issues a token", confirmed.status_code, 200)
    fresh = confirmed.json()["token"]
    check("  which is new", fresh != TOKEN, True)
    check("  and names the business", confirmed.json()["business_name"], "Recovery Mills")
    check("  returns the phone so the browser can sign in",
          confirmed.json()["owner_phone"], f"91{PHONE}")
    check("  the new token works",
          client.get("/api/tenants/me",
                     headers={"Authorization": f"Bearer {fresh}"}).status_code, 200)
    check("  and the old one is dead",
          client.get("/api/tenants/me", headers=live).status_code, 401)

    check("a tampered link is refused",
          client.post("/api/tenants/recover/confirm",
                      json={"token_payload": "rubbish.rubbish"}).status_code, 400)
    check("a link for a deleted tenant is refused",
          client.post("/api/tenants/recover/confirm",
                      json={"token_payload": recovery.sign(uuid.uuid4())}).status_code, 400)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
