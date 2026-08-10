"""Verification for multi-file upload, estimates and dedup.

The rule that matters: uploading the same chat twice must not double the
records. It is tested the way it actually happens — the same export again, and
then a longer export of the same chat, which is what a trader produces when
they re-export next month.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_uploads.py
"""

from __future__ import annotations

import uuid
import zipfile
from datetime import datetime
from io import BytesIO

from fastapi.testclient import TestClient

from app.db import admin_session, tenant_session
from app.models import BusinessProfile, IngestSource, Interaction, Tenant
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


def chat(lines: int, start: int = 1) -> bytes:
    out = []
    for i in range(start, start + lines):
        day = (i % 27) + 1
        out.append(
            f"{day:02d}/06/2026, 10:{i % 60:02d} - Ashok Textiles: "
            f"150 mtr SR-{1000 + i} bhej dena rate 62"
        )
    return "\n".join(out).encode()


TENANT = uuid.uuid4()
with admin_session() as db:
    tenant = Tenant(id=TENANT, business_name="Upload Mills",
                    owner_phone=f"98{uuid.uuid4().int % 10**8:08d}",
                    onboarded_at=datetime.utcnow())
    TOKEN = issue_token(tenant)
    db.add(tenant)
with tenant_session(TENANT) as db:
    db.add(BusinessProfile(tenant_id=TENANT, segments=["wholesaler"], modules={},
                           vocabulary={}, rules={}, examples=[]))

import app.services.dispatch as dispatch_module  # noqa: E402

# The pipeline is not what is under test here.
dispatch_module.dispatch_backfill = lambda *a, **k: "inline"
import app.api.ingest as ingest_module  # noqa: E402
import app.api.tenants as tenants_module  # noqa: E402

ingest_module.dispatch_backfill = lambda *a, **k: "inline"
tenants_module.dispatch_backfill = lambda *a, **k: "inline"

from app.main import app  # noqa: E402

client = TestClient(app)
h = {"Authorization": f"Bearer {TOKEN}"}

print("\n-- the estimate writes nothing --")

est = client.post(
    "/api/ingest/estimate", headers=h,
    files=[("files", ("a.txt", chat(40), "text/plain")),
           ("files", ("b.txt", chat(20, start=500), "text/plain"))],
)
check("an estimate is returned", est.status_code, 200)
body = est.json()
check("  counting both files", len(body["files"]), 2)
check("  with the messages found", body["new_messages"], 60)
check("  and a time an owner can act on", body["estimated_minutes"] >= 1, True)
check("  the wording says what happens", "minute" in body["detail"], True)
with tenant_session(TENANT) as db:
    check("  and NOTHING was stored", db.query(Interaction).count(), 0)

print("\n-- several files in one action --")

resp = client.post(
    "/api/ingest/batch", headers=h,
    files=[("files", ("big.txt", chat(40), "text/plain")),
           ("files", ("small.txt", chat(20, start=500), "text/plain"))],
)
check("the batch is accepted", resp.status_code, 202)
check("  reporting new messages", resp.json()["new_messages"], 60)
with tenant_session(TENANT) as db:
    check("  and all of them landed", db.query(Interaction).count(), 60)
    check("  each with a dedupe key",
          db.query(Interaction).filter(Interaction.dedupe_hash.is_(None)).count(), 0)

print("\n-- the same chat twice --")

again = client.post("/api/ingest/batch", headers=h,
                    files=[("files", ("big.txt", chat(40), "text/plain"))])
check("the second upload is accepted", again.status_code, 202)
check("  but nothing is new", again.json()["new_messages"], 0)
check("  and it says so", again.json()["duplicates"], 40)
with tenant_session(TENANT) as db:
    check("  THE RECORD COUNT DID NOT MOVE", db.query(Interaction).count(), 60)

print("\n-- re-exporting a chat that has grown --")

grown = client.post("/api/ingest/batch", headers=h,
                    files=[("files", ("big.txt", chat(50), "text/plain"))])
check("only the new messages are taken", grown.json()["new_messages"], 10)
check("  the rest recognised as already held", grown.json()["duplicates"], 40)
with tenant_session(TENANT) as db:
    check("  totalling correctly", db.query(Interaction).count(), 70)

print("\n-- the same file picked twice in one action --")

twice = client.post(
    "/api/ingest/batch", headers=h,
    files=[("files", ("x.txt", chat(10, start=9000), "text/plain")),
           ("files", ("x-copy.txt", chat(10, start=9000), "text/plain"))],
)
check("the duplicate copy is dropped", twice.json()["new_messages"], 10)

print("\n-- a zip carrying media --")

buf = BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("_chat.txt",
               "01/06/2026, 10:00 - Ashok Textiles: bill dekho\n"
               "01/06/2026, 10:01 - Ashok Textiles: IMG-9001.jpg (file attached)\n")
    z.writestr("IMG-9001.jpg", b"\xff\xd8\xff\xe0 not really a jpeg")
zipped = client.post("/api/ingest/batch", headers=h,
                     files=[("files", ("chat.zip", buf.getvalue(), "application/zip"))])
check("a zip is read", zipped.status_code, 202)
check("  its media is counted", zipped.json()["media"] >= 1, True)
with tenant_session(TENANT) as db:
    stored = db.query(Interaction).filter(Interaction.media_uri.isnot(None)).count()
    check("  and the file is linked to its message", stored >= 1, True)

print("\n-- one bad file does not sink the batch --")

mixed = client.post(
    "/api/ingest/batch", headers=h,
    files=[("files", ("good.txt", chat(8, start=7000), "text/plain")),
           ("files", ("junk.txt", b"nothing that parses as a chat", "text/plain"))],
)
check("the good file still lands", mixed.json()["new_messages"], 8)
errors = [f for f in mixed.json()["files"] if f["error"]]
check("  and the bad one is reported, not hidden", len(errors), 1)

# Files are processed largest first, so a big unreadable one sorts ahead of a
# small good one. That ordering is what breaks index-based bookkeeping.
big_junk = client.post(
    "/api/ingest/batch", headers=h,
    files=[("files", ("huge-junk.txt", b"x" * 20000, "text/plain")),
           ("files", ("tiny-good.txt", chat(5, start=7500), "text/plain"))],
)
check("a large unreadable file first does not corrupt the counts",
      big_junk.json()["new_messages"], 5)
rows = {f["filename"]: f for f in big_junk.json()["files"]}
check("  the good file's count is on the good file",
      rows["tiny-good.txt"]["messages"], 5)
check("  and the bad one still reports zero and an error",
      (rows["huge-junk.txt"]["messages"], bool(rows["huge-junk.txt"]["error"])), (0, True))

print("\n-- what has been imported is visible --")

sources = client.get("/api/ingest/sources", headers=h)
check("sources are listed", sources.status_code, 200)
check("  one row per file", len(sources.json()) >= 6, True)
check("  newest first",
      sources.json()[0]["created_at"] >= sources.json()[-1]["created_at"], True)
check("  carrying the filename", bool(sources.json()[0]["label"]), True)
with tenant_session(TENANT) as db:
    check("  and a failure is recorded as failed",
          db.query(IngestSource).filter(IngestSource.status == "failed").count() >= 1, True)

print("\n-- limits --")

check("too many files is refused",
      client.post("/api/ingest/batch", headers=h,
                  files=[("files", (f"f{i}.txt", chat(2, start=i * 100), "text/plain"))
                         for i in range(25)]).status_code,
      413)
check("another tenant sees none of this",
      client.get("/api/ingest/sources").status_code, 401)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
