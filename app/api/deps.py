"""Shared FastAPI dependencies.

The tenant comes from the `X-Tenant-Id` header and every handler gets a session
already scoped to it. There is no authentication here yet — the header is
trusted. That is fine while the only clients are the owner's own dashboard and
the demo, and it is the first thing to replace before a second customer's data
lands in the same database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import tenant_session
from app.models.tenant import BusinessProfile


def tenant_id(x_tenant_id: Annotated[uuid.UUID, Header()]) -> uuid.UUID:
    return x_tenant_id


TenantId = Annotated[uuid.UUID, Depends(tenant_id)]


def tenant_db(tid: TenantId) -> Iterator[Session]:
    """A session that can only see this tenant's rows. Commits on clean exit."""
    with tenant_session(tid) as db:
        yield db


TenantDB = Annotated[Session, Depends(tenant_db)]


def business_profile(db: TenantDB, tid: TenantId) -> BusinessProfile:
    profile = db.execute(
        select(BusinessProfile).where(BusinessProfile.tenant_id == tid)
    ).scalars().first()
    if profile is None:
        raise HTTPException(
            status_code=409,
            detail="Tenant has no BusinessProfile yet — run onboarding first.",
        )
    return profile


Profile = Annotated[BusinessProfile, Depends(business_profile)]
