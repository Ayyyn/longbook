"""Seed a demo tenant with believable data and print its token.

For looking at the dashboard without running a Gemini-backed backfill first.

    DATABASE_URL=... PYTHONPATH=. python scripts/seed_demo.py
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Interaction, Party, Tenant
from app.services.auth import issue_token
from app.services.commit import commit_record, queue_for_review

TODAY = date.today()

PARTIES = [
    ("Ashok Textiles", ["Ashok Tex", "ashok bhai"], "+91 98765 43210", "Surat"),
    ("Bharat Fabrics", ["Bharat"], "+91 90000 11111", "Ahmedabad"),
    ("Kishore Silk Mills", [], "+91 91234 56789", "Mumbai"),
]

PAYMENTS = [
    ("Ashok Textiles", "2,50,000", "neft", "UTR889231", TODAY),
    ("Bharat Fabrics", "75,000", "upi", "UPI4482", TODAY),
    ("Kishore Silk Mills", "1,20,000", "cheque", "CHQ 774112", TODAY - timedelta(days=2)),
]

ORDERS = [
    ("Ashok Textiles", "SR-1042", "150", "62", TODAY),
    ("Bharat Fabrics", "SR-1188", "300", "58.50", TODAY),
    ("Kishore Silk Mills", "KR-2201", "80", "145", TODAY - timedelta(days=3)),
]

# Left in the queue on purpose — this is the screen being demonstrated.
QUEUED = [
    ("bhai 200 mtr SR-1042 bhej dena, rate wahi purana",
     {"quality": "SR-1042", "quantity": 200.0, "unit": "meter", "rate": None},
     "Rate not stated; last agreed rate not confirmed.", ["low_confidence(0.62)"]),
    ("payment kar diya aaj",
     {"amount": None, "mode": "neft"},
     "No amount in the message.", ["missing_amount"]),
    ("naya party Rajesh Trading se 50 thaan ka order",
     {"quality": None, "quantity": 50.0, "unit": "thaan", "party": "Rajesh Trading"},
     "Party has not been seen before.", ["unresolved_party"]),
]


def state(tenant_id, interaction_id, record_type, fields, confidence, reason="", flags=None,
          party_id=None, occurred=None):
    return {
        "trace_id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "interaction": {"id": interaction_id, "channel": "whatsapp_export",
                        "occurred_at": occurred or datetime.utcnow()},
        "extraction": {"record_type": record_type, "fields": fields,
                       "confidence": confidence, "reason": reason},
        "resolution": {"party_id": party_id, "method": "alias"},
        "flags": flags or [],
    }


def main() -> None:
    seed = yaml.safe_load(
        (Path("app/profiles/wholesaler.yaml")).read_text(encoding="utf-8")
    )
    phone = f"98{uuid.uuid4().int % 10**8:08d}"

    with admin_session() as db:
        tenant = Tenant(business_name="Diri Textiles", owner_name="Ashokbhai",
                        owner_phone=phone, city="Surat", locale="gu",
                        onboarded_at=datetime.utcnow())
        token = issue_token(tenant)
        db.add(tenant)
        db.flush()
        tenant_id = tenant.id

    with tenant_session(tenant_id) as db:
        db.add(BusinessProfile(tenant_id=tenant_id, segments=seed["segments"],
                               modules=seed["modules"], vocabulary=seed["vocabulary"],
                               rules=seed["rules"], examples=[]))
        for name, aliases, party_phone, city in PARTIES:
            db.add(Party(tenant_id=tenant_id, name=name, aliases=aliases,
                         phone=party_phone, city=city, credit_days=45))

    with tenant_session(tenant_id) as db:
        by_name = {p.name: p.id for p in db.query(Party).all()}

        for party, amount, mode, ref, when in PAYMENTS:
            commit_record(db, state(
                tenant_id, None, "payment",
                {"amount": amount, "mode": mode, "reference": ref,
                 "received_on": when.isoformat()},
                0.96, party_id=by_name[party]))

        for party, quality, qty, rate, when in ORDERS:
            commit_record(db, state(
                tenant_id, None, "order",
                {"quality": quality, "quantity": qty, "unit": "meter", "rate": rate,
                 "order_date": when.isoformat()},
                0.94, party_id=by_name[party]))

        for body, fields, reason, flags in QUEUED:
            interaction = Interaction(tenant_id=tenant_id, channel="whatsapp_export",
                                      sender="Ashok Bhai", body=body,
                                      occurred_at=datetime.utcnow())
            db.add(interaction)
            db.flush()
            queue_for_review(db, state(
                tenant_id, interaction.id, "order" if "amount" not in fields else "payment",
                fields, 0.62, reason, flags,
                party_id=by_name["Ashok Textiles"] if "party" not in fields else None,
            ))

    print(f"tenant_id : {tenant_id}")
    print(f"token     : {token}")
    print("\nPaste the token into the web app to sign in.")


if __name__ == "__main__":
    main()
