"""Shared FastAPI dependencies.

The tenant is derived from a bearer token, never from what the caller says it
is, and every handler gets a session already scoped to it. This is not owner
sign-in — one token per business, issued at onboarding — but it is the
difference between a tenant id being asserted and being possessed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import admin_session, tenant_session
from app.models.tenant import BusinessProfile
from app.services.auth import tenant_for_token

# auto_error=False so a missing header gets our 401 with a WWW-Authenticate
# challenge rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False, description="Tenant token issued at onboarding")

_UNAUTHORIZED = HTTPException(
    status_code=401,
    detail="Missing or invalid tenant token.",
    headers={"WWW-Authenticate": "Bearer"},
)


def tenant_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> uuid.UUID:
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORIZED

    # Unscoped by necessity: resolving the token is what tells us the scope.
    # It reads one indexed column and nothing else.
    with admin_session() as db:
        resolved = tenant_for_token(db, credentials.credentials)

    if resolved is None:
        raise _UNAUTHORIZED
    return resolved


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
