"""Verification for Agent Activity and the submission export.

The export is the XPRIZE evidence and has to work on 15 Aug, so it is tested
against a real database rather than trusted.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_activity.py
"""

from __future__ import annotations

import csv
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

import app.agents.extractor as extractor_module
from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Party, Tenant
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


def fake_extractor(*, model, system, user, **kwargs):
    body = (user or "").lower()
    usage = {"input_tokens": 120, "output_tokens": 40, "cost_usd": 0.00013}
    if "rtgs" in body:
        return {"record_type": "payment", "confidence": 0.95, "reason": "",
                "fields": {"amount": "50000", "mode": "neft"}}, usage
    if "mtr" in body:
        return {"record_type": "order", "confidence": 0.93, "reason": "",
                "fields": {"quality": "SR-1042", "quantity": "150", "rate": "62"}}, usage
    if "kitna" in body:
        return {"record_type": "order", "confidence": 0.4,
                "reason": "Unclear what is being asked for.",
                "fields": {"quality": "ZZ-1", "quantity": "5"}}, usage
    return {"record_type": "noise", "confidence": 1.0, "reason": "", "fields": {}}, usage


extractor_module.generate_json = fake_extractor

EXPORT = """[04/06/26, 10:12:03 AM] Ashok Textiles: 150 mtr SR-1042 chahiye rate 62
[04/06/26, 10:14:11 AM] Ashok Textiles: Good morning ji
[04/06/26, 11:02:45 AM] Ashok Textiles: aaj 50000 rtgs kar diya
[05/06/26, 09:45:00 AM] Ashok Textiles: bhai ZZ-1 ka kitna
"""

TENANT = uuid.uuid4()
with admin_session() as db:
    tenant = Tenant(id=TENANT, business_name="Activity Mills",
                    owner_phone=f"98{uuid.uuid4().int % 10**8:08d}",
                    onboarded_at=datetime.utcnow(), paid_until=datetime.utcnow() + timedelta(days=365))
    TOKEN = issue_token(tenant)
    db.add(tenant)

with tenant_session(TENANT) as db:
    db.add(BusinessProfile(tenant_id=TENANT, segments=["wholesaler"], modules={},
                           vocabulary={}, rules={}, examples=[]))
    db.add(Party(tenant_id=TENANT, name="Ashok Textiles", phone="9876543210"))

from app.main import app  # noqa: E402

client = TestClient(app)
headers = {"Authorization": f"Bearer {TOKEN}"}

client.post("/api/ingest", headers=headers,
            files={"file": ("chat.txt", EXPORT.encode(), "text/plain")})

print("\n-- feed --")

feed = client.get("/api/agents/runs", headers=headers).json()
check("runs are recorded", feed["total"] > 0, True)
item = feed["items"][0]
check("newest first", feed["items"][0]["created_at"] >= feed["items"][-1]["created_at"], True)
check("carries the model", bool(item["model"]), True)
check("carries the prompt version", bool(item["prompt_version"]), True)
check("carries latency", item["latency_ms"] is not None, True)

extractor_runs = [i for i in feed["items"] if i["agent"] == "extractor"]
check("token counts recorded", extractor_runs[0]["input_tokens"], 120)
check("cost recorded", extractor_runs[0]["cost_usd"], 0.00013)
check("the message it was about is shown",
      any("mtr" in (i["subject"] or "") for i in feed["items"]), True)

check("filter by agent",
      {i["agent"] for i in client.get("/api/agents/runs?agent=triage",
                                      headers=headers).json()["items"]},
      {"triage"})

print("\n-- summary --")

summary = client.get("/api/agents/summary", headers=headers).json()
check("totals add up", summary["runs"], feed["total"])
check("nothing overridden yet", summary["overrides"], 0)
check("cost rolled up", summary["cost_usd"] > 0, True)
check("tokens rolled up", summary["input_tokens"] > 0, True)
t = summary["throughput"]
check("throughput counts records, not agent runs", t["records"] > 0, True)
check("  auto-commit rate reported", 0 <= t["auto_commit_rate"] <= 1, True)
check("  written rate reported alongside it", 0 <= t["written_rate"] <= 1, True)
check("  written is never below auto-committed",
      t["written_rate"] >= t["auto_commit_rate"], True)
check("per-agent breakdown present",
      sorted(a["agent"] for a in summary["by_agent"]),
      ["extractor", "resolver", "triage"])

extractor_stat = next(a for a in summary["by_agent"] if a["agent"] == "extractor")
check("average confidence per agent", 0 < extractor_stat["avg_confidence"] <= 1, True)

print("\n-- overrides show up --")

queue = client.get("/api/review/queue", headers=headers).json()
check("the low-confidence item is queued", queue["total"], 1)
queued = queue["items"][0]
client.post(f"/api/review/{queued['extraction_id']}/correct", headers=headers,
            json={"fields": {"quality": "ZZ-1", "quantity": "50"}})

summary = client.get("/api/agents/summary", headers=headers).json()
check("override count rises", summary["overrides"] > 0, True)
check("override rate reported", summary["override_rate"] > 0, True)

overrides = client.get("/api/agents/runs?overrides_only=true", headers=headers).json()
check("override filter works", all(i["human_override"] for i in overrides["items"]), True)
check("  and finds them", overrides["total"] > 0, True)

print("\n-- trace --")

trace_id = queued["trace_id"]
trace = client.get(f"/api/agents/trace/{trace_id}", headers=headers).json()
check("the whole journey is one call",
      [s["agent"] for s in trace["steps"]], ["extractor", "resolver", "triage"])
check("the original message is attached", "kitna" in trace["message"], True)
check("the outcome is attached", trace["record_type"], "order")
check("marked as overridden", trace["human_override"], True)
check("a missing trace 404s",
      client.get(f"/api/agents/trace/{uuid.uuid4()}", headers=headers).status_code, 404)

check("activity needs a token", client.get("/api/agents/summary").status_code, 401)

print("\n-- isolation --")

OTHER = uuid.uuid4()
with admin_session() as db:
    other = Tenant(id=OTHER, business_name="Other", owner_phone=f"97{uuid.uuid4().int % 10**8:08d}", paid_until=datetime.utcnow() + timedelta(days=365))
    OTHER_TOKEN = issue_token(other)
    db.add(other)

other_headers = {"Authorization": f"Bearer {OTHER_TOKEN}"}
check("another tenant sees no runs",
      client.get("/api/agents/runs", headers=other_headers).json()["total"], 0)
check("another tenant cannot open our trace",
      client.get(f"/api/agents/trace/{trace_id}", headers=other_headers).status_code, 404)

print("\n-- export_logs.py --")

out = Path("var/test-export")
shutil.rmtree(out, ignore_errors=True)

from scripts.export_logs import export  # noqa: E402

written = export(out, None, None)
check("three files written", sorted(written), ["agent_daily.csv", "agent_runs.csv",
                                               "api_usage.csv"])
# Unscoped means every tenant, so this only has to contain ours — a shared
# dev database has other tenants' runs in it and that is not a failure.
check("every agent run exported", written["agent_runs.csv"] >= summary["runs"], True)

# Redaction must change columns, never rows: evidence that covers fewer runs
# is not evidence. Same scope, same count, in both modes.
red = export(out, TENANT, 30)
with (out / "agent_runs.csv").open(encoding="utf-8") as handle:
    red_rows = list(csv.DictReader(handle))
check("redacted is the default", "rationale" in red_rows[0], False)
check("  no business name in redacted", "business_name" in red_rows[0], False)
check("  no error text in redacted", "error" in red_rows[0], False)
check("  decision type survives redaction", "decision_type" in red_rows[0], True)
check("  the measurable columns survive",
      [c for c in ["created_at", "agent", "model", "confidence", "latency_ms",
                   "input_tokens", "output_tokens", "cost_usd", "outcome",
                   "human_override"] if c not in red_rows[0]], [])
check("  no customer text anywhere in a redacted row",
      any("Activity Mills" in ",".join(r.values()) for r in red_rows), False)

# The content checks below run against the scoped export, so they assert on
# this tenant's rows rather than whichever tenant happens to sort first.
scoped = export(out, TENANT, 30, redacted=False)
check("scoping to one tenant still works", scoped["agent_runs.csv"], summary["runs"])
check("  redaction drops columns, not rows", red["agent_runs.csv"],
      scoped["agent_runs.csv"])

with (out / "agent_runs.csv").open(encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
required = ["trace_id", "model", "prompt_version", "confidence", "latency_ms",
            "input_tokens", "output_tokens", "cost_usd", "outcome", "human_override"]
check("every observability column is present", [c for c in required if c not in rows[0]], [])
check("business name resolved", {r["business_name"] for r in rows}, {"Activity Mills"})
check("overrides exported as booleans",
      {r["human_override"] for r in rows} <= {"true", "false"}, True)
check("rationale has no newlines", all("\n" not in r["rationale"] for r in rows), True)

with (out / "api_usage.csv").open(encoding="utf-8") as handle:
    usage = list(csv.DictReader(handle))
check("usage rolled up per day", len(usage) >= 1, True)
check("tokens counted", int(usage[0]["input_tokens"]) > 0, True)
check("records committed counted alongside spend", int(usage[0]["records_committed"]) >= 1, True)

with (out / "agent_daily.csv").open(encoding="utf-8") as handle:
    daily = list(csv.DictReader(handle))
check("daily rows per agent", {r["agent"] for r in daily},
      {"extractor", "resolver", "triage"})

empty = export(out, uuid.uuid4(), 30)
check("a tenant with no runs exports headers, not a crash", empty["agent_runs.csv"], 0)

shutil.rmtree(out, ignore_errors=True)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
