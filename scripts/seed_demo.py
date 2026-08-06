"""Seed a demo tenant with believable data and print its token.

For looking at the dashboard without running a Gemini-backed backfill first.

    DATABASE_URL=... PYTHONPATH=. python scripts/seed_demo.py

The Agent Activity screen will be empty afterwards, and deliberately so: this
writes records through `commit.py` directly, so no agent ever runs. Populating
`agent_run` here would put fabricated rows in the same table
`scripts/export_logs.py` exports as submission evidence. To get real activity,
upload an export through /api/ingest with GEMINI_API_KEY set.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Interaction, Invoice, Party, Tenant
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
    ("Ashok Textiles", "SR-1042", "150", "62", TODAY, None),
    ("Bharat Fabrics", "SR-1042", "300", "61", TODAY, None),
    ("Kishore Silk Mills", "SR-1042", "80", "63", TODAY - timedelta(days=3), None),
    # Priced far below the usual rate for this quality — flagged as a deviation.
    ("Bharat Fabrics", "SR-1042", "500", "31", TODAY - timedelta(days=2), None),
    # Promised a fortnight ago and never dispatched — flagged as stalled.
    ("Kishore Silk Mills", "KR-2201", "120", "145", TODAY - timedelta(days=30),
     TODAY - timedelta(days=14)),
]

# Billed and unpaid, so the ageing buckets and overdue alerts have something
# real to show. Ashok is well past 45 days; Kishore is not due yet.
INVOICES = [
    ("Ashok Textiles", "INV-1001", 180000, TODAY - timedelta(days=95)),
    ("Ashok Textiles", "INV-1042", 95000, TODAY - timedelta(days=52)),
    ("Bharat Fabrics", "INV-1103", 60000, TODAY - timedelta(days=20)),
    ("Kishore Silk Mills", "INV-1155", 140000, TODAY + timedelta(days=25)),
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

        for party, quality, qty, rate, when, promised in ORDERS:
            fields = {"quality": quality, "quantity": qty, "unit": "meter", "rate": rate,
                      "order_date": when.isoformat()}
            if promised:
                fields["delivery_date"] = promised.isoformat()
            commit_record(db, state(
                tenant_id, None, "order", fields, 0.94, party_id=by_name[party]))

        for party, number, amount, due in INVOICES:
            db.add(Invoice(tenant_id=tenant_id, party_id=by_name[party], invoice_no=number,
                           invoice_date=due - timedelta(days=1), due_date=due,
                           amount=amount, status="open", source="manual"))

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
