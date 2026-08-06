"""Verification for section 3: onboarding.

Walks the exact three calls a sales meeting makes, with both the Configurator
and the Extractor's model call stubbed.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_onboarding.py
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

import app.agents.configurator as configurator_module
import app.agents.extractor as extractor_module
from app.config import settings
from app.db import admin_session, tenant_session
from app.models import AgentRun, BusinessProfile, Tenant

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


EXPORT = """[04/06/26, 10:12:03 AM] Ashok Bhai: 150 mtr SR-1042 chahiye rate 62 nett
[04/06/26, 10:14:11 AM] Ashok Bhai: Good morning ji
[04/06/26, 11:02:45 AM] Ashok Bhai: aaj 50000 rtgs kar diya
[05/06/26, 09:30:00 AM] Ashok Bhai: LR no 448821 se bhej diya, transporter VRL
"""

configurator_calls: list[dict] = []


def fake_configurator(*, model, system, user, **kwargs):
    configurator_calls.append({"model": model, "user": user})
    return (
        {
            "segments": ["wholesaler"],
            "modules": {"lots": True, "dispatch": True, "job_work": True},
            "vocabulary": {"quantity_units": ["meter", "thaan"], "rate_basis": "per_meter"},
            "rules": {"overdue_days": 30},
            "confidence": 0.88,
            "reason": "Dye lots and LR numbers appear throughout the sample.",
        },
        {"input_tokens": 900, "output_tokens": 120, "cost_usd": 0.002},
    )


def fake_extractor(*, model, system, user, **kwargs):
    body = (user or "").lower()
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    if "rtgs" in body:
        return {"record_type": "payment", "confidence": 0.95, "reason": "",
                "fields": {"party": "Ashok Bhai", "amount": "50000", "mode": "neft"}}, usage
    if "mtr" in body:
        return {"record_type": "order", "confidence": 0.93, "reason": "",
                "fields": {"party": "Ashok Bhai", "quality": "SR-1042",
                           "quantity": "150", "unit": "meter", "rate": "62"}}, usage
    return {"record_type": "noise", "confidence": 1.0, "reason": "", "fields": {}}, usage


configurator_module.generate_json = fake_configurator
extractor_module.generate_json = fake_extractor

from app.main import app  # noqa: E402

client = TestClient(app)
phone = f"98{uuid.uuid4().int % 10**8:08d}"

# --- creating the business ------------------------------------------------

print("\n-- create tenant --")

settings().admin_token = "secret-admin"
settings().env = "prod"

resp = client.post("/api/tenants", json={"business_name": "X", "owner_phone": "9000000001"})
check("no admin token is rejected", resp.status_code, 401)
check("wrong admin token is rejected",
      client.post("/api/tenants", headers={"X-Admin-Token": "nope"},
                  json={"business_name": "X", "owner_phone": "9000000002"}).status_code, 401)

admin = {"X-Admin-Token": "secret-admin"}
resp = client.post("/api/tenants", headers=admin, json={
    "business_name": "Diri Textiles", "owner_name": "Ashok", "owner_phone": phone,
    "city": "Surat", "locale": "gu",
})
check("tenant created", resp.status_code, 201)
created = resp.json()
TENANT = uuid.UUID(created["tenant_id"])
TOKEN = created["token"]
check("a token is handed back once", TOKEN.startswith("tex_"), True)

check("duplicate owner phone is a conflict",
      client.post("/api/tenants", headers=admin,
                  json={"business_name": "Copy", "owner_phone": phone}).status_code, 409)

settings().admin_token = ""
check("unset admin token is refused outside dev",
      client.post("/api/tenants", json={"business_name": "Y",
                                        "owner_phone": "9000000003"}).status_code, 503)
settings().env = "dev"
resp = client.post("/api/tenants", json={"business_name": "Dev Shop",
                                         "owner_phone": f"97{uuid.uuid4().int % 10**8:08d}"})
check("  but allowed on a dev machine", resp.status_code, 201)
settings().admin_token = "secret-admin"

headers = {"Authorization": f"Bearer {TOKEN}"}

# --- the token is the tenant ---------------------------------------------

print("\n-- token scoping --")

me = client.get("/api/tenants/me", headers=headers).json()
check("token identifies the business", me["business_name"], "Diri Textiles")
check("locale carried through", me["locale"], "gu")
check("not onboarded yet", me["onboarded_at"], None)
check("no profile yet", me["profile"], None)
check("ingest refuses before onboarding",
      client.post("/api/ingest", headers=headers,
                  files={"file": ("c.txt", EXPORT.encode(), "text/plain")}).status_code, 409)

# --- the sample -----------------------------------------------------------

print("\n-- sample upload --")

resp = client.post("/api/tenants/sample", headers=headers,
                   files={"file": ("chat.txt", EXPORT.encode(), "text/plain")})
check("sample accepted", resp.status_code, 202)
sample = resp.json()
check("four messages read", sample["interactions"], 4)
check("preview is verbatim", sample["preview"][0], "150 mtr SR-1042 chahiye rate 62 nett")
check("sample works without a profile", "profile" in str(resp.json()).lower(), False)

# --- the interview --------------------------------------------------------

print("\n-- configure --")

resp = client.post("/api/tenants/configure", headers=headers, json={
    "segments": ["wholesaler"],
    "what_you_sell": "cotton and poly-cotton shirting",
    "units": "meter, thaan",
    "tracks_lots": True,
    "gives_credit": True,
    "credit_days": 45,
})
check("configure succeeded", resp.status_code, 200)
result = resp.json()
profile = result["profile"]

check("profile came from the configurator", profile["source"], "configurator")
check("confidence surfaced", profile["confidence"], 0.88)
check("agent findings applied", profile["modules"]["job_work"], True)
check("seed fills what the agent did not decide", profile["modules"]["credit_ledger"], True)
check("agent overrides the seed", profile["rules"]["overdue_days"], 30)
check("seed rules survive", profile["rules"]["rate_deviation_pct"], 20)
check("owner's segments win", profile["segments"], ["wholesaler"])
check("messages queued", result["pending_interactions"], 4)

check("interview text reached the agent",
      "cotton and poly-cotton shirting" in configurator_calls[0]["user"], True)
check("  along with the message sample",
      "SR-1042" in configurator_calls[0]["user"], True)
check("  on the configured deep model", configurator_calls[0]["model"], settings().model_deep)

with tenant_session(TENANT) as db:
    stored = db.query(BusinessProfile).filter_by(tenant_id=TENANT).one()
    check("profile persisted", stored.vocabulary["rate_basis"], "per_meter")
    check("version starts at 1", stored.version, "1")
    runs = db.query(AgentRun).filter_by(agent="configurator").all()
    check("the configurator run was logged", len(runs), 1)
    check("  with its cost", float(runs[0].cost_usd), 0.002)

# --- backfill ran behind it ----------------------------------------------

print("\n-- backfill --")

me = client.get("/api/tenants/me", headers=headers).json()
check("onboarded_at stamped", me["onboarded_at"] is not None, True)
check("profile now visible", me["profile"]["segments"], ["wholesaler"])
check("interactions counted", me["interactions"], 4)

queue = client.get("/api/review/queue", headers=headers).json()

# Party seeding runs before the backfill, so the Resolver has somebody to
# attribute records to and the first backfill commits instead of queueing.
with tenant_session(TENANT) as db:
    from app.models import Order, Party, Payment

    check("the counterparty was seeded from the chat", db.query(Party).count(), 1)
    check("  named after the sender", db.query(Party).one().name, "Ashok Bhai")
    check("the order auto-committed", db.query(Order).count(), 1)
    check("the payment auto-committed", db.query(Payment).count(), 1)

check("nothing was left in the queue", queue["total"], 0)

check("ingest works now that a profile exists",
      client.post("/api/ingest", headers=headers,
                  files={"file": ("more.txt", EXPORT.encode(), "text/plain")}).status_code, 202)

# --- re-running onboarding -----------------------------------------------

print("\n-- re-configure --")

resp = client.post("/api/tenants/configure", headers=headers,
                   json={"segments": ["wholesaler", "retail"]})
check("re-configure succeeds", resp.status_code, 200)
check("version bumped", resp.json()["profile"]["version"], "2")
check("both segments kept", resp.json()["profile"]["segments"], ["wholesaler", "retail"])

with tenant_session(TENANT) as db:
    check("still one profile row", db.query(BusinessProfile).filter_by(tenant_id=TENANT).count(), 1)

# --- the agent failing must not dead-end onboarding ----------------------

print("\n-- configurator failure --")


def broken(*args, **kwargs):
    raise RuntimeError("gemini unavailable")


configurator_module.generate_json = broken

other_phone = f"96{uuid.uuid4().int % 10**8:08d}"
other = client.post("/api/tenants", headers=admin, json={
    "business_name": "Retail Shop", "owner_phone": other_phone,
}).json()
other_headers = {"Authorization": f"Bearer {other['token']}"}

client.post("/api/tenants/sample", headers=other_headers,
            files={"file": ("chat.txt", EXPORT.encode(), "text/plain")})
resp = client.post("/api/tenants/configure", headers=other_headers,
                   json={"segments": ["retail"]})
check("onboarding still completes", resp.status_code, 200)
check("  from the seed", resp.json()["profile"]["source"], "seed")
check("  and says why", "unavailable" in resp.json()["profile"]["rationale"].lower(), True)
check("  retail seed chosen", resp.json()["profile"]["modules"]["lots"], False)
check("  retail overdue days", resp.json()["profile"]["rules"]["overdue_days"], 15)

with admin_session() as db:
    check("the failure was still logged as an agent run",
          db.query(AgentRun).filter_by(agent="configurator", outcome="error").count(), 1)

configurator_module.generate_json = fake_configurator

# --- isolation ------------------------------------------------------------

print("\n-- isolation --")

check("another tenant sees its own profile",
      client.get("/api/tenants/me", headers=other_headers).json()["business_name"], "Retail Shop")
check("  and none of our interactions",
      client.get("/api/tenants/me", headers=other_headers).json()["interactions"], 4)

with admin_session() as db:
    check("tenants are distinct", db.query(Tenant).count() >= 3, True)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
