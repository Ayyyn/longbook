"""Runs the pipeline over a tenant's conversation windows.

A 90-day export is several thousand messages, which is minutes of model calls —
far past any HTTP timeout. So ingestion persists the raw `Interaction` rows
synchronously (fast, and the owner's data is safe the moment the upload
returns) and this runs behind a job id.

Progress lives on the window, not the message: `extracted_hash` versus
`content_hash` says whether a window has been through the pipeline as it
currently stands. That is what makes a re-run a no-op, and what makes a window
that later gains a message re-extract exactly once.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.config import settings
from app.db import tenant_session
from app.models.finance import Payment
from app.models.ingestion import Extraction, Interaction
from app.models.orders import Dispatch, Order
from app.models.party import Party
from app.models.tenant import BusinessProfile
from app.models.window import ExtractionWindow
from app.pipeline import build_pipeline
from app.services.windowing import load_segment, pending_windows, sync_windows

# Transient job state — the counts come from the DB, this only carries what the
# database cannot know: that a run is in flight, and why it stopped.
_RUNS: dict[uuid.UUID, dict[str, Any]] = {}

PARTY_HINT_LIMIT = 40

# Windows are independent, so they run concurrently. The ceiling is the model's
# rate limit, not the CPU: app/llm.py paces every call globally, so extra
# workers past what the quota allows just queue on that lock. Each worker takes
# its own session — a SQLAlchemy Session is not thread-safe.
DEFAULT_WORKERS = 8

# Records the pipeline wrote itself and no human has touched. Safe to withdraw
# when a window is re-extracted; anything a human has seen is not.
_MACHINE_STATUSES = ("auto_committed", "needs_review")

_COMMITTED_MODELS = {"order": Order, "payment": Payment, "dispatch": Dispatch}


def _party_hints(db, tenant_id: uuid.UUID) -> list[str]:
    """Grounding for the Extractor: real customer names beat a blank prompt."""
    return list(
        db.execute(
            select(Party.name).where(Party.tenant_id == tenant_id).limit(PARTY_HINT_LIMIT)
        ).scalars().all()
    )


def _counterparty(segment, tenant_id) -> tuple[str | None, str | None]:
    """Who the owner was talking to in this window.

    The busiest sender that is not the owner. A 1:1 export names them by
    contact name, a group by number; either way the Resolver can attribute a
    record whose text never says who it is from.
    """
    counts: dict[tuple[str | None, str | None], int] = {}
    for message in segment.messages:
        key = (message.sender, message.sender_phone)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None, None
    name, phone = max(counts, key=lambda k: counts[k])
    return name, phone


def _withdraw_previous(db, tenant_id: uuid.UUID, window: ExtractionWindow) -> int:
    """Retract what a previous pass over this window wrote.

    Only machine-written records are withdrawn. If a human accepted or
    corrected anything from this window, the window is marked `curated` and
    left alone entirely — re-extraction must never overwrite their work.
    """
    previous = db.execute(
        select(Extraction).where(
            Extraction.tenant_id == tenant_id, Extraction.window_id == window.id
        )
    ).scalars().all()
    if not previous:
        return 0

    if any(e.status not in _MACHINE_STATUSES for e in previous):
        window.outcome = "curated"
        return -1

    withdrawn = 0
    for extraction in previous:
        model = _COMMITTED_MODELS.get(extraction.committed_type or "")
        if model is not None and extraction.committed_id:
            record = db.get(model, extraction.committed_id)
            if record is not None:
                db.delete(record)
        extraction.status = "superseded"
        extraction.committed_type = None
        extraction.committed_id = None
        withdrawn += 1

    db.flush()
    return withdrawn


def _process_window(
    tenant_id: uuid.UUID, window_id: uuid.UUID, hints: list[str]
) -> tuple[str, str | None]:
    """Run one window through the pipeline, in its own session and transaction.

    Returns (outcome, error). Per-window isolation is what makes concurrency
    safe — a SQLAlchemy Session is not thread-safe — and what stops one bad
    conversation costing the rest of the export.
    """
    with tenant_session(tenant_id) as db:
        window = db.get(ExtractionWindow, window_id)
        if window is None:
            return "gone", None

        segment = load_segment(db, window)
        if not segment.messages:
            window.extracted_hash = window.content_hash
            window.outcome = "extracted"
            return "empty", None

        if _withdraw_previous(db, tenant_id, window) < 0:
            return "curated", None  # the owner's version stands

        profile = db.execute(
            select(BusinessProfile).where(BusinessProfile.tenant_id == tenant_id)
        ).scalars().first()
        graph = build_pipeline(db, tenant_id, profile)

        name, phone = _counterparty(segment, tenant_id)
        media = next(
            (m for m in segment.messages if m.media_uri and m.media_kind == "image"),
            None,
        )
        state = {
            "trace_id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "window": {
                "id": window.id,
                "text": segment.render(),
                "message_count": len(segment.messages),
                "anchor_id": segment.anchor.id,
                "channel": segment.anchor.channel,
                "ended_at": segment.ended_at,
                "counterparty_name": name,
                "counterparty_phone": phone,
                "party_hints": hints,
                "media_uri": media.media_uri if media else None,
                "media_kind": media.media_kind if media else None,
            },
        }

        try:
            final = graph.invoke(state)
            # Attribute each record to the messages the model cited.
            for record, result in zip(
                final.get("records", []), final.get("results", []), strict=False
            ):
                ids = [segment.id_for_index(n) for n in record.get("source_lines", [])]
                ids = [str(i) for i in ids if i]
                if ids and result.get("extraction_id"):
                    stored = db.get(Extraction, uuid.UUID(result["extraction_id"]))
                    if stored is not None:
                        stored.source_message_ids = ids

            window.extracted_hash = window.content_hash
            window.outcome = "extracted"
            window.last_error = None
            return "extracted", None
        except Exception as exc:  # noqa: BLE001 - one window must not stop the batch
            db.rollback()
            stale = db.get(ExtractionWindow, window_id)
            if stale is not None:
                stale.outcome = "failed"
                stale.last_error = f"{type(exc).__name__}: {exc}"[:500]
            return "failed", f"window {window_id}: {type(exc).__name__}: {exc}"


def run_backfill(
    tenant_id: uuid.UUID,
    job_id: uuid.UUID | None = None,
    workers: int | None = None,
    on_progress=None,
) -> None:
    """Segment into windows, then push every stale window through the pipeline.

    Windows are independent, so they run concurrently. The real ceiling is the
    model's rate limit rather than the pool size — app/llm.py paces every call
    globally — so this mostly buys back the time each request spends waiting on
    the network instead of on quota.
    """
    _RUNS[job_id] = {
        "tenant_id": tenant_id,
        "state": "running",
        "errors": [],
        "started_at": datetime.utcnow(),
        "total": 0,
        "done": 0,
    }
    lock = threading.Lock()

    def note(outcome: str, error: str | None) -> None:
        with lock:
            _RUNS[job_id]["done"] += 1
            if error:
                _RUNS[job_id]["errors"].append(error)
            if on_progress:
                on_progress(_RUNS[job_id]["done"], _RUNS[job_id]["total"], outcome)

    try:
        with tenant_session(tenant_id) as db:
            profile = db.execute(
                select(BusinessProfile).where(BusinessProfile.tenant_id == tenant_id)
            ).scalars().first()
            sync_windows(db, tenant_id, profile)
            db.commit()

            hints = _party_hints(db, tenant_id)
            window_ids = [w.id for w in pending_windows(db, tenant_id)]

        _RUNS[job_id]["total"] = len(window_ids)
        if on_progress:
            on_progress(0, len(window_ids), "starting")

        pool_size = max(1, min(workers or settings().backfill_workers, len(window_ids) or 1))
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            futures = {
                pool.submit(_process_window, tenant_id, window_id, hints): window_id
                for window_id in window_ids
            }
            for future in as_completed(futures):
                try:
                    outcome, error = future.result()
                except Exception as exc:  # noqa: BLE001 - a dead worker is one window
                    outcome, error = "failed", f"{type(exc).__name__}: {exc}"
                note(outcome, error)

        _RUNS[job_id]["state"] = "done"
    except Exception as exc:  # noqa: BLE001 - surfaced through the job endpoint
        _RUNS[job_id]["state"] = "failed"
        _RUNS[job_id]["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        _RUNS[job_id]["finished_at"] = datetime.utcnow()


def job_status(db, tenant_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
    """Counts straight from the interactions and windows the job created."""
    in_job = [
        Interaction.tenant_id == tenant_id,
        Interaction.attributes["job_id"].astext == str(job_id),
    ]

    total = db.execute(select(func.count()).select_from(Interaction).where(*in_job)).scalar_one()

    # Windows the job's messages landed in — a window can span two uploads, so
    # progress is reported over whatever those messages belong to now.
    window_ids = select(Interaction.window_id).where(*in_job, Interaction.window_id.isnot(None))
    processed = db.execute(
        select(func.count())
        .select_from(Interaction)
        .where(
            *in_job,
            Interaction.window_id.in_(
                select(ExtractionWindow.id).where(
                    ExtractionWindow.tenant_id == tenant_id,
                    ExtractionWindow.extracted_hash == ExtractionWindow.content_hash,
                )
            ),
        )
    ).scalar_one()

    by_status = dict(
        db.execute(
            select(Extraction.status, func.count())
            .where(
                Extraction.tenant_id == tenant_id,
                Extraction.window_id.in_(window_ids),
                Extraction.status != "superseded",
            )
            .group_by(Extraction.status)
        ).all()
    )

    # Only trust the in-memory run if it belongs to this tenant — the registry
    # is process-wide and its errors are not something to hand to a stranger.
    run = _RUNS.get(job_id) or {}
    if run.get("tenant_id") != tenant_id:
        run = {}

    state = run.get("state")
    if state is None:
        state = "done" if total and processed >= total else "unknown"

    return {
        "job_id": job_id,
        "state": state,
        "total": total,
        "processed": processed,
        "windows_total": run.get("total", 0),
        "windows_done": run.get("done", 0),
        "committed": by_status.get("auto_committed", 0),
        "needs_review": by_status.get("needs_review", 0),
        "discarded": by_status.get("rejected", 0),
        "logged": by_status.get("logged", 0),
        "errors": run.get("errors", [])[:20],
    }
