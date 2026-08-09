"""Ingestion routes.

The upload is the onboarding magic trick: the owner exports a chat, and a few
minutes later their last 90 days of orders and outstandings are on screen. So
this endpoint does the fast, safe half synchronously — parse and persist the
raw `Interaction` rows — and hands the slow half (a model call per message) to
a background job. The owner gets a job id back before their phone locks.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from sqlalchemy import select

from app.api.deps import Profile, TenantDB, TenantId
from app.models.ingestion import Interaction
from app.schemas.ingest import IngestAccepted, JobStatus
from app.services.backfill import job_status, run_backfill
from app.services.intake import IntakeError, interactions_from_upload

router = APIRouter()


def save_upload(file: UploadFile) -> Path:
    """Spool to disk so the parsers can seek — a zip cannot be read from a stream."""
    suffix = Path(file.filename or "").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        return Path(tmp.name)


@router.post("", response_model=IngestAccepted, status_code=202)
@router.post("/", response_model=IngestAccepted, status_code=202, include_in_schema=False)
def ingest_upload(
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    background: BackgroundTasks,
    file: UploadFile = File(...),
) -> IngestAccepted:
    """Accept a WhatsApp export (.txt/.zip), an Excel sheet, or a photo."""
    job_id = uuid.uuid4()
    tmp_path = save_upload(file)
    try:
        intake = interactions_from_upload(tid, file.filename, tmp_path, job_id)
    except IntakeError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    db.add_all(intake.interactions)
    db.flush()

    # Commit before queueing: the background task opens its own session and
    # must not race the request's transaction.
    db.commit()
    background.add_task(run_backfill, tid, job_id)

    return IngestAccepted(
        job_id=job_id,
        interactions=len(intake.interactions),
        skipped=intake.skipped,
        kind=intake.kind,
        detail=(
            f"{len(intake.interactions)} interactions stored; "
            "extraction running in the background."
        ),
    )


@router.post("/resume", response_model=JobStatus | None, status_code=202)
def resume_backfill(
    background: BackgroundTasks, tid: TenantId, db: TenantDB, profile: Profile
) -> JobStatus | None:
    """Pick a stalled backfill back up.

    The backfill is a background task inside the API process, so anything that
    replaces the container — a deploy, an instance recycle, a crash — kills it
    mid-run with no error anywhere. What is left is a job that has processed
    some of its messages and will never process the rest, which the dashboard
    can only render as a progress bar frozen forever.

    Re-running is safe and cheap: extraction is keyed on a window's content
    hash, so windows already done are skipped and only the unfinished ones cost
    a model call. Reusing the original job id keeps the owner's progress count
    continuous rather than restarting it at zero.
    """
    job_id = db.execute(
        select(Interaction.attributes["job_id"].astext)
        .where(
            Interaction.tenant_id == tid,
            Interaction.attributes["job_id"].astext.isnot(None),
        )
        .order_by(Interaction.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not job_id:
        raise HTTPException(404, "Nothing has been uploaded for this tenant yet.")

    background.add_task(run_backfill, tid, uuid.UUID(job_id))
    return JobStatus(**job_status(db, tid, uuid.UUID(job_id)))


@router.get("/jobs/latest", response_model=JobStatus | None)
def latest_job(tid: TenantId, db: TenantDB) -> JobStatus | None:
    """The most recent backfill for this tenant, or null if there has never been one.

    The dashboard needs this to show progress after a reload. The job id is
    handed back once, at upload; without a way to ask "what is running now?"
    the owner who closes the tab during a ten-minute backfill comes back to a
    screen that looks empty rather than busy.
    """
    row = db.execute(
        select(Interaction.attributes["job_id"].astext)
        .where(
            Interaction.tenant_id == tid,
            Interaction.attributes["job_id"].astext.isnot(None),
        )
        .order_by(Interaction.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not row:
        return None
    status = job_status(db, tid, uuid.UUID(row))
    return JobStatus(**status) if status["total"] else None


@router.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: uuid.UUID, tid: TenantId, db: TenantDB) -> JobStatus:
    status = job_status(db, tid, job_id)
    if status["total"] == 0:
        raise HTTPException(404, f"No ingestion job {job_id} for this tenant.")
    return JobStatus(**status)
