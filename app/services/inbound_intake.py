"""Turning forwarded mail into interactions the pipeline already understands.

The point of routing through `Interaction` rather than inventing an email
record type: everything downstream — windowing, extraction, resolution,
triage, the review queue, the audit trail — already works on interactions. A
second shape would need all of that rebuilt, and the second copy is the one
that quietly stops deduping.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from email.utils import parsedate_to_datetime

from sqlalchemy import select

from app.models.ingestion import IngestSource, Interaction
from app.models.tenant import BusinessProfile, Tenant
from app.services.inbound import InboundMail, slug_for
from app.services.intake import dedupe_hash
from app.services.storage import store_media

log = logging.getLogger(__name__)


def ensure_slug(db, tenant: Tenant) -> str:
    """Give a tenant its forwarding tag if it does not have one yet."""
    if not tenant.inbound_slug:
        tenant.inbound_slug = slug_for(tenant.id)
        db.flush()
    return tenant.inbound_slug


def _when(mail: InboundMail) -> datetime:
    if mail.occurred_at:
        try:
            parsed = parsedate_to_datetime(mail.occurred_at)
            # Naive throughout the rest of the system; a tz-aware value here
            # would blow up every comparison it later takes part in.
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except Exception:  # noqa: BLE001 - a bad Date header is not fatal
            pass
    return datetime.utcnow()


def store_mail(db, tenant_id: uuid.UUID, mail: InboundMail, job_id: uuid.UUID) -> int:
    """Write one forwarded mail and its attachments. Returns rows added."""
    occurred = _when(mail)
    thread = f"email:{mail.sender[:80]}"
    added = 0

    body = "\n".join(part for part in [mail.subject, mail.body] if part).strip()
    if body:
        digest = dedupe_hash(tenant_id, thread, occurred, mail.sender, body, None)
        exists = db.execute(
            select(Interaction.id).where(
                Interaction.tenant_id == tenant_id,
                Interaction.dedupe_hash == digest,
            )
        ).scalars().first()
        if not exists:
            db.add(
                Interaction(
                    tenant_id=tenant_id,
                    channel="email",
                    sender=mail.sender,
                    occurred_at=occurred,
                    body=body,
                    media_kind="none",
                    thread_key=thread,
                    dedupe_hash=digest,
                    attributes={"job_id": str(job_id), "subject": mail.subject},
                )
            )
            added += 1

    for filename, kind, payload in mail.attachments:
        digest = dedupe_hash(tenant_id, thread, occurred, mail.sender, None, filename)
        exists = db.execute(
            select(Interaction.id).where(
                Interaction.tenant_id == tenant_id,
                Interaction.dedupe_hash == digest,
            )
        ).scalars().first()
        if exists:
            continue
        uri = store_media(tenant_id, filename, payload)
        db.add(
            Interaction(
                tenant_id=tenant_id,
                channel="email",
                sender=mail.sender,
                occurred_at=occurred,
                body=f"{mail.subject} — attachment: {filename}".strip(" —"),
                media_uri=uri,
                media_kind="image" if kind.startswith("image/") else "document",
                thread_key=thread,
                dedupe_hash=digest,
                attributes={"job_id": str(job_id), "filename": filename},
            )
        )
        added += 1

    return added


def deliver(db, mails: list[InboundMail]) -> dict:
    """Route a batch of parsed mail to the tenants it was addressed to.

    Returns a summary rather than raising: one tenant's malformed attachment
    should not stop another's invoice from landing.
    """
    if not mails:
        return {"mails": 0, "delivered": 0, "unmatched": 0, "tenants": []}

    by_slug: dict[str, list[InboundMail]] = {}
    for mail in mails:
        by_slug.setdefault(mail.slug, []).append(mail)

    rows = db.execute(
        select(Tenant).where(Tenant.inbound_slug.in_(list(by_slug)))
    ).scalars().all()
    tenants = {t.inbound_slug: t for t in rows}

    delivered = 0
    unmatched = 0
    touched: list[dict] = []

    for slug, batch in by_slug.items():
        tenant = tenants.get(slug)
        if tenant is None:
            # Mail to an alias nobody owns. Counted so it shows up as a number
            # rather than vanishing, but not stored anywhere.
            unmatched += len(batch)
            log.warning("Inbound mail for unknown alias %s", slug)
            continue

        job_id = uuid.uuid4()
        added = 0
        for mail in batch:
            try:
                added += store_mail(db, tenant.id, mail, job_id)
            except Exception:  # noqa: BLE001 - one bad mail, not the whole run
                log.exception("Could not store forwarded mail for %s", tenant.id)

        db.add(
            IngestSource(
                tenant_id=tenant.id,
                kind="email_forward",
                label=f"{len(batch)} forwarded email{'s' if len(batch) != 1 else ''}",
                job_id=job_id,
                messages=added,
                media=sum(len(m.attachments) for m in batch),
            )
        )
        db.flush()
        delivered += added

        has_profile = db.execute(
            select(BusinessProfile.id).where(BusinessProfile.tenant_id == tenant.id)
        ).scalars().first()
        touched.append(
            {
                "tenant_id": str(tenant.id),
                "business_name": tenant.business_name,
                "mails": len(batch),
                "records": added,
                "job_id": str(job_id) if (added and has_profile) else None,
            }
        )

    return {
        "mails": len(mails),
        "delivered": delivered,
        "unmatched": unmatched,
        "tenants": touched,
    }
