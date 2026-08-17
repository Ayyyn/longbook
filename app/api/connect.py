"""Connected sources: a connected mailbox, or a forwarding alias.

Two ways in, and the difference is who has to remember something. Forwarding
works everywhere and needs no grant, but it only carries the mail the owner
thought to forward. A connected mailbox carries all of it, which is the only
version where the books stay current without anybody tending them.

Connecting goes through Nylas rather than Google directly. `gmail.readonly` is
a restricted scope: until a CASA assessment is paid for and passed, the consent
screen stays in Testing mode, where refresh tokens expire after seven days —
every customer reconnecting weekly, and silently not syncing when they forget.
Nylas has passed that assessment already. See app/services/nylas.py.

The grant id is never in a response. It reads the owner's mail; the only part
of it safe to show back is the address.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import TenantDB, TenantId
from app.api.jobs import require_scheduler
from app.config import settings
from app.db import admin_session, tenant_session
from app.models.mail_account import MailAccount
from app.models.tenant import Tenant
from app.services import inbound, mail_sync, nylas
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


# --------------------------------------------------------------------------
# Connected mailbox
# --------------------------------------------------------------------------


class MailboxInfo(BaseModel):
    """What the connect screen shows. Note what is absent: the grant id."""

    available: bool
    accounts: list[dict]
    detail: str


class ConnectStart(BaseModel):
    url: str


def _redirect_uri() -> str:
    return f"{settings().api_url.rstrip('/')}/api/connect/mail/callback"


def _state_secret() -> str:
    """What the callback's `state` is signed with.

    The admin token: it already exists, it is already in Secret Manager, and
    rotating it invalidating in-flight connections is the correct behaviour
    rather than a side effect.
    """
    return settings().admin_token or settings().nylas_api_key


def _describe(account: MailAccount) -> dict:
    return {
        "id": str(account.id),
        "email": account.email,
        "provider": account.provider,
        "status": account.status,
        "synced_through": account.synced_through.isoformat() if account.synced_through else None,
        "last_checked_at": (
            account.last_checked_at.isoformat() if account.last_checked_at else None
        ),
        "last_error": account.last_error,
    }


@router.get("/mail", response_model=MailboxInfo)
def mailbox_status(tid: TenantId, db: TenantDB) -> MailboxInfo:
    """Which mailboxes this business has connected."""
    if not nylas.configured():
        return MailboxInfo(
            available=False,
            accounts=[],
            detail=(
                "Connecting a mailbox is not switched on for this deployment "
                "yet. Use the forwarding address instead."
            ),
        )

    accounts = db.execute(select(MailAccount)).scalars().all()
    if not accounts:
        detail = (
            "Connect the mailbox your invoices and purchase orders arrive in. "
            "Longbook reads it and nothing else — it never sends mail from your "
            "account."
        )
    elif any(a.status == "revoked" for a in accounts):
        detail = (
            "A connected mailbox has stopped syncing. Connect it again to pick "
            "up where it left off."
        )
    else:
        detail = "New mail is read every few minutes."

    return MailboxInfo(
        available=True,
        accounts=[_describe(a) for a in accounts],
        detail=detail,
    )


@router.post("/mail/connect", response_model=ConnectStart)
def mailbox_connect(tid: TenantId, dest: str = "add") -> ConnectStart:
    """Where to send the owner to grant access.

    Returns the URL rather than redirecting: the call is made by the dashboard
    with a bearer token, and a browser following a redirect would not carry
    one. The dashboard sends them on.
    """
    if not nylas.configured():
        raise HTTPException(503, "Connecting a mailbox is not switched on yet.")

    # Where to come back to. Setup is the important case: connecting a mailbox
    # from step 3 used to land the owner on Add data, which is to say outside
    # the setup they were half way through.
    state = nylas.sign_state(str(tid), _state_secret(), int(time.time()), dest)
    return ConnectStart(url=nylas.auth_url(_redirect_uri(), state))


@router.get("/mail/callback")
def mailbox_callback(code: str | None = None, state: str | None = None,
                     error: str | None = None) -> RedirectResponse:
    """Where the provider sends the owner back.

    Unauthenticated by necessity — it is reached by a browser redirect that
    carries no bearer token — so `state` is the whole of the authorisation.
    It is signed with a server secret and carries the tenant id, which is why
    the tenant is read out of it rather than taken as a parameter: a tenant id
    in the query string would let anyone attach their mailbox to any business.
    """
    dash = settings().dashboard_url.rstrip("/")

    if error or not code or not state:
        return RedirectResponse(f"{dash}/add?mail=failed", status_code=303)

    read = nylas.read_state(state, _state_secret())
    if not read:
        # Forged, tampered with, or simply older than fifteen minutes. All
        # three get the same answer.
        return RedirectResponse(f"{dash}/add?mail=expired", status_code=303)
    tenant_id, dest = read

    try:
        payload = nylas.exchange_code(code, _redirect_uri())
    except nylas.NylasError:
        return RedirectResponse(f"{dash}/add?mail=failed", status_code=303)

    grant_id = payload.get("grant_id")
    if not grant_id:
        return RedirectResponse(f"{dash}/add?mail=failed", status_code=303)

    email = payload.get("email") or ""
    provider = payload.get("provider") or ""
    if not email:
        # The token response does not always carry the address; the grant
        # itself does, and it is what the owner identifies the mailbox by.
        try:
            detail = nylas.grant(grant_id)
            email = detail.get("email") or ""
            provider = provider or detail.get("provider") or ""
        except nylas.NylasError:
            pass

    tid = uuid.UUID(tenant_id)
    with tenant_session(tid) as db:
        existing = db.execute(
            select(MailAccount).where(MailAccount.email == email)
        ).scalars().first() if email else None

        if existing is not None:
            # Reconnecting the same mailbox. The watermark is kept, so the
            # months already read are not read again.
            existing.grant_id = grant_id
            existing.provider = provider or existing.provider
            existing.status = "active"
            existing.last_error = None
        else:
            db.add(MailAccount(
                tenant_id=tid,
                grant_id=grant_id,
                email=email,
                provider=provider,
                status="active",
            ))

    return RedirectResponse(f"{dash}/{dest}?mail=connected", status_code=303)


@router.post("/mail/sync")
def mailbox_sync(tid: TenantId) -> dict:
    """Read the connected mailboxes now, rather than waiting for the sweep.

    Exists because the first thing an owner does after connecting is look for
    their mail, and "in a few minutes" is not an answer at that moment.
    """
    results = mail_sync.sync_tenant(tid)
    for row in results:
        if row.get("job_id"):
            dispatch_backfill(tid, uuid.UUID(row["job_id"]), None)
    return {
        "accounts": len(results),
        "records": sum(r["records"] for r in results),
        # The first pull of a mailbox with years in it does not fit in one
        # request. `more` tells the screen to come back for the rest rather
        # than telling the owner their history is in when half of it is not.
        "more": any(r.get("more") for r in results),
        "results": results,
    }


@router.delete("/mail/{account_id}")
def mailbox_disconnect(account_id: uuid.UUID, tid: TenantId, db: TenantDB) -> dict:
    """Stop reading a mailbox.

    Revokes at Nylas as well as here — leaving a live grant behind for a
    mailbox the owner has disconnected would mean we still hold the ability
    to read mail they believe they have taken back.

    Records already extracted stay. Disconnecting is "stop reading my mail",
    not "delete what you learned from it", and deleting the second on the
    strength of the first would be a nasty surprise.
    """
    account = db.get(MailAccount, account_id)
    if account is None:
        raise HTTPException(404, "No such mailbox.")
    if account.grant_id:
        nylas.revoke(account.grant_id)
    db.delete(account)
    return {"disconnected": True}


@router.post("/mail/sweep", dependencies=[Depends(require_scheduler)])
def mailbox_sweep() -> dict:
    """Every connected mailbox for every business. Called by Cloud Scheduler."""
    # Longer budget than the interactive path: nobody is waiting on this one,
    # and it is what carries a large first pull the rest of the way.
    summary = mail_sync.sync_all(budget=700.0)
    for row in summary["results"]:
        if row.get("job_id"):
            with admin_session() as db:
                account = db.get(MailAccount, uuid.UUID(row["account_id"]))
                tenant_id = account.tenant_id if account else None
            if tenant_id:
                dispatch_backfill(tenant_id, uuid.UUID(row["job_id"]), None)
    return summary


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
