"""Pulling a connected mailbox into the same pipeline as everything else.

The whole design here is one sentence: a Nylas message becomes an `InboundMail`
and goes through `store_mail`, exactly as a forwarded one does. There is no
second dedupe, no second attachment store, no second extraction path. If mail
that arrives by grant behaved differently from mail that arrives by forward,
every bug in this file would be a bug nobody could reproduce in the other path.

The watermark is the only genuinely new idea. Nylas filters by `received_after`
in whole seconds, so `synced_through` holds the received-at of the newest
message actually taken and the next run asks for everything at or after it. A
second of overlap costs nothing — `store_mail` dedupes on content — while a
second of gap loses an invoice with no error anywhere.

No model calls here. This is transport plus bookkeeping.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from app.db import admin_session, tenant_session
from app.models.ingestion import IngestSource
from app.models.mail_account import MailAccount
from app.models.tenant import Tenant
from app.services import nylas
from app.services.access import access_for
from app.services.inbound_intake import store_mail

log = logging.getLogger(__name__)


def sync_account(db, account: MailAccount) -> dict:
    """Read one mailbox and store what is new. Returns a summary.

    Does not raise on a Nylas failure: the sweep runs across every business,
    and one revoked grant must not stop the rest from syncing. The failure is
    recorded on the row instead, which is what the connect screen reads to
    tell the owner their mail stopped.
    """
    result = {
        "account_id": str(account.id),
        "email": account.email,
        "messages": 0,
        "records": 0,
        "job_id": None,
        "error": None,
    }

    since = account.synced_through or nylas.default_since()
    try:
        messages = nylas.list_messages(account.grant_id, since)
    except nylas.NylasError as exc:
        # 401/403 is the grant itself; anything else is a bad day for Nylas
        # and the mailbox is still fine.
        if exc.status in (401, 403):
            account.status = "revoked"
        account.last_error = str(exc)[:300]
        account.last_checked_at = datetime.utcnow()
        result["error"] = str(exc)[:300]
        log.warning("nylas sync failed for %s: %s", account.id, exc)
        return result

    account.status = "active"
    account.last_error = None
    account.last_checked_at = datetime.utcnow()

    if not messages:
        return result

    job_id = uuid.uuid4()
    added = 0
    newest = account.synced_through
    attachments = 0

    for message in messages:
        try:
            mail = nylas.to_inbound(account.grant_id, message)
            added += store_mail(db, account.tenant_id, mail, job_id)
            attachments += len(mail.attachments)
        except Exception:  # noqa: BLE001 - one bad mail, not the whole mailbox
            log.exception("Could not store Nylas message %s", message.get("id"))
            continue
        # Only advance past mail we actually took. A message that threw stays
        # behind the watermark and is retried on the next run.
        stamp = nylas.received_at(message)
        if stamp and (newest is None or stamp > newest):
            newest = stamp

    if newest:
        account.synced_through = newest

    result["messages"] = len(messages)
    result["records"] = added

    if added:
        # The same row the forwarding path writes, so connected mail appears
        # in "Imported so far" alongside everything else rather than arriving
        # from nowhere.
        db.add(
            IngestSource(
                tenant_id=account.tenant_id,
                kind="mailbox",
                label=f"{added} message{'s' if added != 1 else ''} from {account.email}",
                job_id=job_id,
                messages=added,
                media=attachments,
            )
        )
        result["job_id"] = str(job_id)

    db.flush()
    return result


def sync_tenant(tenant_id: uuid.UUID) -> list[dict]:
    """Every connected mailbox for one business."""
    out: list[dict] = []
    with tenant_session(tenant_id) as db:
        accounts = db.execute(
            select(MailAccount).where(MailAccount.status == "active")
        ).scalars().all()
        for account in accounts:
            out.append(sync_account(db, account))
    return out


def sync_all() -> dict:
    """Every connected mailbox for every business. Called by the scheduler.

    Expired tenants are skipped rather than synced. Locking somebody out of
    the app while still reading their mail every ten minutes is not a thing
    we should be doing, and it costs Nylas quota for records nobody can see.
    """
    with admin_session() as db:
        pairs = db.execute(
            select(MailAccount.tenant_id, MailAccount.id)
            .where(MailAccount.status == "active")
        ).all()
        tenant_ids = list({row[0] for row in pairs})
        tenants = db.execute(
            select(Tenant).where(Tenant.id.in_(tenant_ids))
        ).scalars().all() if tenant_ids else []
        allowed = [t.id for t in tenants if access_for(t).allowed]

    results: list[dict] = []
    for tid in allowed:
        try:
            results.extend(sync_tenant(tid))
        except Exception:  # noqa: BLE001 - one business, not the sweep
            log.exception("Mailbox sweep failed for tenant %s", tid)

    return {
        "accounts": len(results),
        "skipped": len(tenant_ids) - len(allowed) if tenant_ids else 0,
        "records": sum(r["records"] for r in results),
        "results": results,
    }
