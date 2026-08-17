"""Scheduled job triggers.

Cloud Run has no in-process cron worth trusting — an instance that scales to
zero takes its timers with it — so the schedule lives in Cloud Scheduler and
hits this endpoint. Authentication is a shared scheduler token rather than a
tenant token, because the run is deliberately cross-tenant.

The endpoint runs every tenant whose local close of business is *now*, which
is what makes "close of business" mean the owner's evening rather than UTC's.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select

from app.config import settings
from app.db import admin_session, tenant_session
from app.models.tenant import BusinessProfile, Tenant
from app.api.tenants import require_admin
from app.services.digest import DEFAULT_DIGEST_HOUR, run_digest_for_tenant, tenant_local_hour

router = APIRouter()


def require_scheduler(x_scheduler_token: Annotated[str | None, Header()] = None) -> None:
    expected = settings().scheduler_token
    if not expected:
        if settings().env != "dev":
            raise HTTPException(503, "SCHEDULER_TOKEN is not configured on this deployment.")
        return
    if not x_scheduler_token or not secrets.compare_digest(x_scheduler_token, expected):
        raise HTTPException(401, "Invalid scheduler token.")


def _digest_hour(profile: BusinessProfile | None) -> int:
    rules = (profile.rules if profile else {}) or {}
    return int(rules.get("digest_hour", DEFAULT_DIGEST_HOUR))


@router.post("/digest", dependencies=[Depends(require_scheduler)])
def run_digests(
    tenant_id: uuid.UUID | None = Query(None, description="Run one tenant, ignoring the hour"),
    force: bool = Query(False, description="Run regardless of the tenant's local hour"),
    as_of: date | None = Query(None),
) -> dict[str, Any]:
    """Run the close-of-business digest for every tenant that is due."""
    hour = tenant_local_hour()

    with admin_session() as db:
        candidates = db.execute(
            select(Tenant.id).where(Tenant.is_active.is_(True))
            if tenant_id is None
            else select(Tenant.id).where(Tenant.id == tenant_id)
        ).scalars().all()

    results: list[dict[str, Any]] = []
    skipped = 0

    for candidate in candidates:
        with tenant_session(candidate) as db:
            tenant = db.get(Tenant, candidate)
            if tenant is None:
                continue
            profile = db.execute(
                select(BusinessProfile).where(BusinessProfile.tenant_id == candidate)
            ).scalars().first()

            if not (force or tenant_id) and _digest_hour(profile) != hour:
                skipped += 1
                continue

            # Each tenant in its own session and its own transaction: one
            # tenant's failure must not roll back another's watermark.
            try:
                results.append(run_digest_for_tenant(db, tenant, as_of).as_dict())
            except Exception as exc:  # noqa: BLE001 - reported, never fatal to the run
                results.append(
                    {"tenant_id": str(candidate), "error": f"{type(exc).__name__}: {exc}"}
                )

    return {
        "local_hour": hour,
        "ran": len(results),
        "skipped_not_due": skipped,
        "results": results,
    }


@router.post("/reextract", dependencies=[Depends(require_admin)])
def reextract(tenant_id: uuid.UUID | None = Query(default=None)) -> dict:
    """Read again everything the pipeline has not successfully read.

    An operator lever, not a schedule. It exists because there was no way to
    say "try that again" after a bug ate a class of records: every photograph,
    PDF and voice note failed extraction for as long as media was handed to
    Gemini as a gs:// URI, and once the fix landed there was nothing that would
    revisit the windows it had spoiled short of asking customers to re-upload.

    Safe to run at any time, and safe to run twice. A window is only picked up
    when its content hash differs from the hash it was last extracted at, so
    work already done costs nothing, and `curated` windows — ones a human has
    corrected — are never touched.
    """
    from app.models.window import ExtractionWindow
    from app.services.dispatch import dispatch_backfill

    with admin_session() as db:
        stale = select(
            ExtractionWindow.tenant_id, ExtractionWindow.id,
            ExtractionWindow.outcome, ExtractionWindow.last_error,
        ).where(
            ExtractionWindow.outcome != "curated",
            (ExtractionWindow.extracted_hash.is_(None))
            | (ExtractionWindow.extracted_hash != ExtractionWindow.content_hash),
        )
        if tenant_id is not None:
            stale = stale.where(ExtractionWindow.tenant_id == tenant_id)
        rows = db.execute(stale).all()
        targets = sorted({row[0] for row in rows})
        # Why each one is stuck, not merely that it is. A window that keeps
        # failing for the same reason needs the reason, or the only tool left
        # is running this again and hoping.
        blocked = [
            {"tenant_id": str(r[0]), "window_id": str(r[1]),
             "outcome": r[2], "last_error": (r[3] or "")[:200]}
            for r in rows if r[2] == "failed"
        ][:20]

    started = []
    for tid in targets:
        job_id = uuid.uuid4()
        try:
            how = dispatch_backfill(tid, job_id, None)
            started.append({"tenant_id": str(tid), "job_id": str(job_id), "how": how})
        except Exception as exc:  # noqa: BLE001 - one tenant, not the sweep
            started.append({"tenant_id": str(tid), "error": f"{type(exc).__name__}: {exc}"})

    return {"tenants": len(targets), "started": started, "blocked": blocked}
