"""Create (or reuse) a stable tenant for eval runs.

The verification scripts truncate the database, so the eval needs a tenant of
its own that survives them. Prints the id for `--tenant`.

    DATABASE_URL=... PYTHONPATH=. python scripts/eval_tenant.py
"""

from __future__ import annotations

import uuid
from pathlib import Path

import yaml
from sqlalchemy import select

from app.db import admin_session, tenant_session
from app.models import BusinessProfile, Party, Tenant

# Fixed so re-running is idempotent and a saved baseline keeps meaning the same
# thing across runs.
EVAL_TENANT = uuid.UUID("e0a1c0de-0000-4000-8000-00000000e0a1")
EVAL_PHONE = "9000000001"

PARTIES = ["Ravi Fabrics Surat", "Shree Krishna Textiles"]


def main() -> None:
    seed = yaml.safe_load(
        Path("app/profiles/universal.yaml").read_text(encoding="utf-8")
    )

    with admin_session() as db:
        tenant = db.get(Tenant, EVAL_TENANT)
        if tenant is None:
            db.add(Tenant(id=EVAL_TENANT, business_name="Eval Harness",
                          owner_phone=EVAL_PHONE, city="Surat", locale="en"))

    with tenant_session(EVAL_TENANT) as db:
        profile = db.execute(
            select(BusinessProfile).where(BusinessProfile.tenant_id == EVAL_TENANT)
        ).scalars().first()
        if profile is None:
            db.add(BusinessProfile(
                tenant_id=EVAL_TENANT, segments=seed["segments"], modules=seed["modules"],
                vocabulary=seed["vocabulary"], rules=seed["rules"], examples=[],
            ))
        existing = {
            name for name in db.execute(select(Party.name)).scalars().all()
        }
        for name in PARTIES:
            if name not in existing:
                db.add(Party(tenant_id=EVAL_TENANT, name=name))

    print(EVAL_TENANT)


if __name__ == "__main__":
    main()
