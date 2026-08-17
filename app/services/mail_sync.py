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
import time
import uuid
from datetime import datetime

from sqlalchemy import select

from app.config import settings
from app.db import admin_session, tenant_session
from app.models.ingestion import IngestSource
from app.models.mail_account import MailAccount
from app.models.tenant import Tenant
from app.services import nylas
from app.services.access import access_for
from app.services.inbound_intake import store_mail

log = logging.getLogger(__name__)


def sync_account(db, account: MailAccount, budget: float = 240.0) -> dict:
    """Read one mailbox and store what is new. Returns a summary.

    Pages until the mailbox is exhausted, the message cap is reached, or the
    time budget runs out — whichever comes first. The budget exists because
    the first sync of a mailbox that has been open for years is not a request
    anybody can wait on, and a Cloud Run request that runs past its timeout
    loses everything it had done. Stopping early is free: the watermark means
    the next call resumes exactly where this one stopped, and `more` in the
    result tells the caller there is more to come.

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
        "more": False,
        "error": None,
    }

    # A mailbox nobody has synced yet gets the initial lookback; after that
    # the watermark is the only thing that decides.
    since = account.synced_through or nylas.default_since()
    started = time.monotonic()
    cap = settings().nylas_max_messages

    job_id = uuid.uuid4()
    added = 0
    seen = 0
    attachments = 0
    newest = account.synced_through
    cursor: str | None = None

    while True:
        try:
            messages, cursor = nylas.list_messages(account.grant_id, since, cursor=cursor)
        except nylas.NylasError as exc:
            # 401/403 is the grant itself; anything else is a bad day for
            # Nylas and the mailbox is still fine.
            if exc.status in (401, 403):
                account.status = "revoked"
            account.last_error = str(exc)[:300]
            account.last_checked_at = datetime.utcnow()
            result["error"] = str(exc)[:300]
            log.warning("nylas sync failed for %s: %s", account.id, exc)
            # Whatever earlier pages stored is kept and the watermark still
            # moves — a failure on page nine should not re-read pages one
            # through eight next time.
            break

        account.status = "active"
        account.last_error = None

        for message in messages:
            try:
                mail = nylas.to_inbound(account.grant_id, message)
                added += store_mail(db, account.tenant_id, mail, job_id)
                attachments += len(mail.attachments)
            except Exception:  # noqa: BLE001 - one bad mail, not the mailbox
                log.exception("Could not store Nylas message %s", message.get("id"))
                continue
            seen += 1
            # Only advance past mail we actually took. A message that threw
            # stays behind the watermark and is retried on the next run.
            stamp = nylas.received_at(message)
            if stamp and (newest is None or stamp > newest):
                newest = stamp

        if not cursor or not messages:
            break
        if seen >= cap or time.monotonic() - started > budget:
            # Out of budget rather than out of mail.
            result["more"] = True
            break

    account.last_checked_at = datetime.utcnow()
    if newest:
        account.synced_through = newest

    result["messages"] = seen
    result["records"] = added
    if result["error"] and not seen:
        return result

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


def sync_tenant(tenant_id: uuid.UUID, budget: float = 240.0) -> list[dict]:
    """Every connected mailbox for one business."""
    out: list[dict] = []
    with tenant_session(tenant_id) as db:
        accounts = db.execute(
            select(MailAccount).where(MailAccount.status == "active")
        ).scalars().all()
        # Split the budget so one huge mailbox does not starve the second one
        # the owner connected.
        share = budget / max(len(accounts), 1)
        for account in accounts:
            out.append(sync_account(db, account, budget=share))
    return out


def sync_all(budget: float = 700.0) -> dict:
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
    # Shared across businesses, so one tenant's first pull cannot eat the
    # whole sweep and leave everybody else unsynced for ten minutes.
    share = budget / max(len(allowed), 1)
    for tid in allowed:
        try:
            results.extend(sync_tenant(tid, budget=share))
        except Exception:  # noqa: BLE001 - one business, not the sweep
            log.exception("Mailbox sweep failed for tenant %s", tid)

    return {
        "accounts": len(results),
        "skipped": len(tenant_ids) - len(allowed) if tenant_ids else 0,
        "records": sum(r["records"] for r in results),
        "more": any(r.get("more") for r in results),
        "results": results,
    }
