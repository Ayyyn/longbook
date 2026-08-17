"""Verification for forwarded-mail intake.

The rule that matters most: mail addressed to one tenant's alias must never
land in another's books. Everything else here is about not losing an invoice
and not reading it twice.

    DATABASE_URL=... PYTHONPATH=. python scripts/verify_inbound.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage

from app.db import admin_session, tenant_session
from app.models import Interaction, Tenant
from app.services import inbound
from app.services.inbound_intake import deliver, ensure_slug

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


def make_mail(to: str, subject: str, body: str, attach=None) -> bytes:
    m = EmailMessage()
    m["From"] = "Ravi Mills <accounts@ravimills.example>"
    m["To"] = to
    m["Subject"] = subject
    m["Date"] = "Mon, 10 Aug 2026 11:04:00 +0530"
    m.set_content(body)
    if attach:
        name, kind, payload = attach
        main, sub = kind.split("/", 1)
        m.add_attachment(payload, maintype=main, subtype=sub, filename=name)
    return m.as_bytes()


A = uuid.uuid4()
B = uuid.uuid4()
with admin_session() as db:
    for tid, name in [(A, "Alias Mills A"), (B, "Alias Mills B")]:
        db.add(Tenant(id=tid, business_name=name,
                      owner_phone=f"98{uuid.uuid4().int % 10**8:08d}",
                      onboarded_at=datetime.utcnow(), paid_until=datetime.utcnow() + timedelta(days=365)))

with admin_session() as db:
    slug_a = ensure_slug(db, db.get(Tenant, A))
    slug_b = ensure_slug(db, db.get(Tenant, B))

print("\n-- the alias --")

check("each tenant gets a slug", bool(slug_a) and bool(slug_b), True)
check("  and they differ", slug_a != slug_b, True)
check("  stable across calls", slug_a, inbound.slug_for(A))
check("  and short enough to read out", len(slug_a) <= 24, True)
check("  the tenant id is not in it", str(A) in slug_a, False)

print("\n-- parsing --")

parsed = inbound.parse_message(
    make_mail(f"ops+{slug_a}@example.com", "Invoice 8892", "Bill attached, 450 meters.")
)
check("a forwarded mail is parsed", parsed is not None, True)
check("  the alias is recovered", parsed.slug, slug_a)
check("  with the subject", parsed.subject, "Invoice 8892")
check("  and the body", "450 meters" in parsed.body, True)

check("mail with no alias is ignored",
      inbound.parse_message(make_mail("ops@example.com", "hi", "no tag")), None)

# A Gmail auto-forward filter puts the alias in Delivered-To, not To.
raw = make_mail("someone-else@example.com", "PO 1180", "See attached")
delivered_to = b"Delivered-To: ops+" + slug_b.encode() + b"@example.com\r\n" + raw
check("Delivered-To is honoured", inbound.parse_message(delivered_to).slug, slug_b)

with_pdf = inbound.parse_message(
    make_mail(f"ops+{slug_a}@example.com", "Invoice", "attached",
              attach=("inv.pdf", "application/pdf", b"%PDF-1.4 fake"))
)
check("a PDF attachment is kept", len(with_pdf.attachments), 1)
check("  with its filename", with_pdf.attachments[0][0], "inv.pdf")

with_logo = inbound.parse_message(
    make_mail(f"ops+{slug_a}@example.com", "Hello", "regards",
              attach=("logo.svg", "image/svg+xml", b"<svg/>"))
)
check("decoration is not", len(with_logo.attachments), 0)

print("\n-- delivery --")

mails = [
    inbound.parse_message(make_mail(f"ops+{slug_a}@example.com", "Invoice 1",
                                    "450 meters at 62")),
    inbound.parse_message(make_mail(f"ops+{slug_b}@example.com", "Invoice 2",
                                    "200 pieces at 88")),
    inbound.parse_message(make_mail(f"ops+{slug_a}@example.com", "PO 9",
                                    "order confirmed",
                                    attach=("po.pdf", "application/pdf", b"%PDF-1.4 x"))),
]
with admin_session() as db:
    summary = deliver(db, mails)

check("all three delivered", summary["mails"], 3)
check("  none unmatched", summary["unmatched"], 0)

with tenant_session(A) as db:
    a_rows = db.query(Interaction).count()
with tenant_session(B) as db:
    b_rows = db.query(Interaction).count()

check("tenant A got its two mails plus the attachment", a_rows, 3)
check("TENANT B GOT ONLY ITS OWN", b_rows, 1)

with tenant_session(A) as db:
    bodies = " ".join(i.body or "" for i in db.query(Interaction).all())
    check("  and none of B's figures reached A", "88" in bodies, False)
    check("  the attachment was stored",
          db.query(Interaction).filter(Interaction.media_uri.isnot(None)).count(), 1)

print("\n-- the same mail twice --")

with admin_session() as db:
    deliver(db, mails)
with tenant_session(A) as db:
    check("re-delivering adds nothing", db.query(Interaction).count(), 3)

print("\n-- mail to nobody --")

orphan = inbound.parse_message(make_mail("ops+doesnotexist@example.com", "x", "y"))
with admin_session() as db:
    result = deliver(db, [orphan])
check("unknown alias is counted", result["unmatched"], 1)
check("  and stored nowhere", result["delivered"], 0)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
