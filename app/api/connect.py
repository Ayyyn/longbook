"""Connected sources: forwarding today, OAuth when the console client exists.

Forwarding leads deliberately. `gmail.readonly` is a restricted scope, so
until a CASA assessment is paid for the consent screen stays in Testing mode,
where refresh tokens expire after seven days — every customer reconnecting
weekly, and silently not syncing when they forget. A forwarding alias has no
token, nothing to expire, and no cap on how many businesses can use it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import TenantDB, TenantId
from app.api.jobs import require_scheduler
from app.db import admin_session
from app.models.tenant import Tenant
from app.services import inbound
from app.services.dispatch import dispatch_backfill
from app.services.inbound_intake import deliver, ensure_slug

router = APIRouter()


class InboundInfo(BaseModel):
    configured: bool
    address: str | None
    how: list[str]
    limits: list[str]


class OAuthStatus(BaseModel):
    available: bool
    connected: bool
    detail: str


@router.get("/inbound", response_model=InboundInfo)
def inbound_address(tid: TenantId, db: TenantDB) -> InboundInfo:
    """This tenant's forwarding address, and how to use it."""
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "No such tenant.")

    if not inbound.configured():
        return InboundInfo(
            configured=False,
            address=None,
            how=[],
            limits=["Email forwarding is not switched on for this deployment yet."],
        )

    slug = ensure_slug(db, tenant)
    return InboundInfo(
        configured=True,
        address=inbound.address_for(slug),
        how=[
            "Forward any invoice, purchase order or quotation to this address.",
            "It is yours alone — mail sent to it lands in your books and nobody "
            "else's.",
            "To do it automatically: in Gmail open Settings, then Filters and "
            "Blocked Addresses, create a filter for the senders you buy from, and "
            "tick Forward it to this address.",
            "PDFs, photos and spreadsheets attached to the mail are read too.",
        ],
        limits=[
            "Mail is checked every few minutes, not instantly.",
            "Attachments over 20 MB are skipped.",
        ],
    )


@router.get("/gmail/status", response_model=OAuthStatus)
def gmail_status(tid: TenantId) -> OAuthStatus:
    """Whether the OAuth path can be offered at all.

    Honest rather than aspirational: without a console client there is nothing
    to connect to, and saying "Connect Gmail" on a button that cannot work is
    worse than saying it is not ready.
    """
    from app.config import settings

    cfg = settings()
    if not (cfg.gmail_client_id and cfg.gmail_client_secret):
        return OAuthStatus(
            available=False,
            connected=False,
            detail=(
                "Direct Gmail connection is not switched on yet. Use the "
                "forwarding address instead — it does the same job and does not "
                "need reconnecting."
            ),
        )
    return OAuthStatus(
        available=True,
        connected=False,
        detail=(
            "Connecting reads new invoices and purchase orders automatically. "
            "While the app is unverified, Google expires the connection every "
            "seven days and it has to be reconnected."
        ),
    )


@router.post("/inbound/poll", dependencies=[Depends(require_scheduler)])
def poll_inbound() -> dict:
    """Read the mailbox and route what is in it. Called by Cloud Scheduler.

    Cross-tenant, so it authenticates with the scheduler token rather than a
    tenant one — one mailbox serves every business.
    """
    mails = inbound.fetch_unseen()
    if not mails:
        return {"mails": 0, "delivered": 0, "unmatched": 0, "tenants": []}

    with admin_session() as db:
        summary = deliver(db, mails)

    # Dispatch outside the session so a long-running job launch does not hold
    # a transaction open.
    for row in summary["tenants"]:
        if row.get("job_id"):
            dispatch_backfill(uuid.UUID(row["tenant_id"]), uuid.UUID(row["job_id"]), None)
    return summary
