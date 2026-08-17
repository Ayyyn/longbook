"""Throwaway verification for section 1: tenant guard + matching passes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db import TenantIsolationError, admin_session, tenant_session
from app.models import Party, Tenant
from app.services.matching import exact_alias_match, phone_match, shortlist_parties

ok = fail = 0


def check(label: str, got, want) -> None:
    global ok, fail
    if got == want:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}\n          got={got!r}\n         want={want!r}")


a_id, b_id = uuid.uuid4(), uuid.uuid4()
suffix = uuid.uuid4().hex[:6]

with admin_session() as db:
    db.add(Tenant(id=a_id, business_name="Ashok Tex Mills", owner_phone=f"9000{suffix}", paid_until=datetime.utcnow() + timedelta(days=365)))
    db.add(Tenant(id=b_id, business_name="Rival Traders", owner_phone=f"9111{suffix}", paid_until=datetime.utcnow() + timedelta(days=365)))

with tenant_session(a_id) as db:
    db.add(Party(name="Ashok Textiles", aliases=["Ashok Tex", "ashok bhai", "A.T. Mumbai"],
                 phone="+91 98765 43210"))
    db.add(Party(name="Ashok Trading Co", aliases=[], phone="9123456789"))
    db.add(Party(name="Bharat Fabrics", aliases=[], phone=None))

with tenant_session(b_id) as db:
    db.add(Party(name="Ashok Textiles", aliases=["Ashok Tex"], phone="+91 98765 43210"))

print("\n-- tenant isolation --")
with tenant_session(a_id) as db:
    names = sorted(n for (n,) in db.execute(select(Party.name)).all())
    check("session A sees only A's parties", names,
          ["Ashok Textiles", "Ashok Trading Co", "Bharat Fabrics"])

    tenants = [t.business_name for t in db.execute(select(Tenant)).scalars().all()]
    check("session A sees only tenant A", tenants, ["Ashok Tex Mills"])

    p = db.execute(select(Party).where(Party.name == "Bharat Fabrics")).scalars().one()
    check("new row was stamped with tenant A", p.tenant_id, a_id)

with tenant_session(b_id) as db:
    names = sorted(n for (n,) in db.execute(select(Party.name)).all())
    check("session B sees only B's parties", names, ["Ashok Textiles"])

try:
    with tenant_session(a_id) as db:
        db.add(Party(tenant_id=b_id, name="Smuggled In"))
    check("cross-tenant insert raises", "no error", "TenantIsolationError")
except TenantIsolationError:
    check("cross-tenant insert raises", "TenantIsolationError", "TenantIsolationError")

print("\n-- exact_alias_match --")
with tenant_session(a_id) as db:
    check("exact name, different case", exact_alias_match(db, a_id, "ASHOK TEXTILES").name,
          "Ashok Textiles")
    check("alias hit", exact_alias_match(db, a_id, "ashok tex").name, "Ashok Textiles")
    check("alias with punctuation", exact_alias_match(db, a_id, "a.t. mumbai").name,
          "Ashok Textiles")
    check("alias, padded", exact_alias_match(db, a_id, "  Ashok Bhai  ").name, "Ashok Textiles")
    check("no match", exact_alias_match(db, a_id, "Someone Else"), None)
    check("empty name", exact_alias_match(db, a_id, ""), None)

print("\n-- phone_match --")
with tenant_session(a_id) as db:
    for label, raw in [("stored format", "+91 98765 43210"), ("bare 10 digit", "9876543210"),
                       ("leading zero", "09876543210"), ("country code", "+919876543210")]:
        hit = phone_match(db, a_id, raw)
        check(label, hit.name if hit else None, "Ashok Textiles")
    check("too short", phone_match(db, a_id, "12345"), None)
    check("none", phone_match(db, a_id, None), None)

print("\n-- shortlist_parties --")
with tenant_session(a_id) as db:
    got = shortlist_parties(db, a_id, "Ashok Textile")
    check("ranked, tenant-scoped", [c.name for c in got], ["Ashok Textiles"])
    check("scores descending", got == sorted(got, key=lambda c: -c.score), True)
    check("near-exact scores high", got[0].score > 0.8, True)

    loose = shortlist_parties(db, a_id, "Ashok Textile", threshold=0.25)
    check("lower threshold widens net", [c.name for c in loose],
          ["Ashok Textiles", "Ashok Trading Co"])

    by_alias = shortlist_parties(db, a_id, "A.T. Mumbai")
    check("alias drives the score", by_alias[0].name, "Ashok Textiles")
    check("alias score beats name score", by_alias[0].score > 0.9, True)
    check("has .id and .score", (isinstance(got[0].id, uuid.UUID), isinstance(got[0].score, float)),
          (True, True))
    check("misspelling still matches", bool(shortlist_parties(db, a_id, "Ashok Texttiles")), True)
    check("unrelated name filtered out", shortlist_parties(db, a_id, "Zenith Silk Mills"), [])
    check("empty name", shortlist_parties(db, a_id, "  "), [])
    check("limit respected", len(shortlist_parties(db, a_id, "Ashok", limit=1)), 1)

print(f"\n{ok} passed, {fail} failed")
raise SystemExit(1 if fail else 0)
