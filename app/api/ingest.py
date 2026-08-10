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
from app.models.ingestion import IngestSource, Interaction
from app.schemas.ingest import (
    EstimateOut,
    FileEstimateOut,
    IngestAccepted,
    JobStatus,
    SourceOut,
)
from app.services.backfill import job_status
from app.services.dispatch import dispatch_backfill
from app.services.intake import IntakeError
from app.services.uploads import estimate_only, max_files, parse_many

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
    """Accept a WhatsApp export (.txt/.zip), an Excel sheet, or a photo.

    Goes through the same parse-and-dedupe path as a batch: once messages
    carry a unique key, a route that inserts without checking it does not
    create duplicates, it raises an IntegrityError and loses the whole upload.
    """
    job_id = uuid.uuid4()
    tmp_path = save_upload(file)
    spooled = [(file.filename or "upload", tmp_path)]
    try:
        rows, estimate = parse_many(db, tid, spooled, job_id)
    except IntakeError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    first = estimate.files[0] if estimate.files else None
    if first and first.error:
        raise HTTPException(first.status_code, first.error)

    db.add_all(rows)
    db.add(
        IngestSource(
            tenant_id=tid, kind="upload", label=first.filename if first else None,
            job_id=job_id, messages=len(rows),
            duplicates=first.duplicates if first else 0,
            skipped=first.skipped if first else 0,
            media=first.media if first else 0,
            bytes=first.bytes if first else 0,
        )
    )
    db.flush()

    # Commit before queueing: the background task opens its own session and
    # must not race the request's transaction.
    db.commit()
    if rows:
        dispatch_backfill(tid, job_id, background)

    detail = (
        f"{len(rows)} interactions stored; extraction running in the background."
        if rows
        else "Everything in this file has already been read."
    )
    return IngestAccepted(
        job_id=job_id,
        interactions=len(rows),
        skipped=first.skipped if first else 0,
        kind=first.kind if first else "unknown",
        detail=detail,
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

    dispatch_backfill(tid, uuid.UUID(job_id), background)
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


def _spool_uploads(files: list[UploadFile]) -> list[tuple[str, Path]]:
    if not files:
        raise HTTPException(400, "No files were sent.")
    if len(files) > max_files():
        raise HTTPException(413, f"Send at most {max_files()} files at once.")
    return [(f.filename or "upload", save_upload(f)) for f in files]


def _cleanup(spooled: list[tuple[str, Path]]) -> None:
    for _, path in spooled:
        path.unlink(missing_ok=True)


def _to_out(estimate) -> EstimateOut:
    if estimate.new_messages:
        detail = (
            f"{estimate.new_messages} new messages. "
            f"Reading them takes about {estimate.minutes} "
            f"{'minute' if estimate.minutes == 1 else 'minutes'}."
        )
        if estimate.duplicates:
            detail += f" {estimate.duplicates} were already read and will be skipped."
    elif estimate.duplicates:
        detail = "Everything in these files has already been read."
    else:
        detail = "No messages found in these files."

    return EstimateOut(
        files=[FileEstimateOut(**vars(f)) for f in estimate.files],
        new_messages=estimate.new_messages,
        duplicates=estimate.duplicates,
        media=estimate.media,
        estimated_minutes=estimate.minutes,
        detail=detail,
    )


@router.post("/estimate", response_model=EstimateOut)
def estimate_upload(
    tid: TenantId, db: TenantDB, files: list[UploadFile] = File(...)
) -> EstimateOut:
    """Say what these files contain, and write nothing.

    Runs the real parser rather than guessing from file size — the point is
    that the number shown is the number that will happen.
    """
    spooled = _spool_uploads(files)
    try:
        return _to_out(estimate_only(db, tid, spooled))
    finally:
        _cleanup(spooled)


@router.post("/batch", response_model=EstimateOut, status_code=202)
def ingest_many(
    tid: TenantId,
    db: TenantDB,
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> EstimateOut:
    """Take several files in one action and start one backfill over all of them."""
    job_id = uuid.uuid4()
    spooled = _spool_uploads(files)
    try:
        rows, estimate = parse_many(db, tid, spooled, job_id)
    finally:
        _cleanup(spooled)

    if rows:
        db.add_all(rows)

    for f in estimate.files:
        db.add(
            IngestSource(
                tenant_id=tid,
                kind="upload",
                label=f.filename,
                job_id=job_id,
                messages=f.messages,
                duplicates=f.duplicates,
                skipped=f.skipped,
                media=f.media,
                bytes=f.bytes,
                status="failed" if f.error else "done",
                detail=f.error,
            )
        )
    db.flush()
    db.commit()

    # Nothing new means nothing to extract; starting a job would only produce
    # a progress bar that finishes instantly and confuses the owner.
    if rows:
        dispatch_backfill(tid, job_id, background)

    return _to_out(estimate)


@router.get("/sources", response_model=list[SourceOut])
def list_sources(tid: TenantId, db: TenantDB, limit: int = 50) -> list[SourceOut]:
    """What has been imported and when, so coverage is visible rather than guessed."""
    rows = db.execute(
        select(IngestSource)
        .where(IngestSource.tenant_id == tid)
        .order_by(IngestSource.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        SourceOut(
            id=r.id, kind=r.kind, label=r.label, messages=r.messages or 0,
            duplicates=r.duplicates or 0, media=r.media or 0,
            status=r.status or "done", detail=r.detail, created_at=r.created_at,
        )
        for r in rows
    ]
