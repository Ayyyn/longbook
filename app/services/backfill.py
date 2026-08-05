"""Runs the pipeline over a batch of freshly ingested interactions.

A 90-day export is several thousand messages, which is minutes of model calls —
far past any HTTP timeout. So ingestion persists the raw `Interaction` rows
synchronously (fast, and the owner's data is safe the moment the upload
returns) and this runs behind a job id.

Progress is derived from the database rather than held in memory, because the
one question the owner asks during onboarding — "is it done yet?" — must still
have an answer after a redeploy.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.db import tenant_session
from app.models.ingestion import Interaction
from app.models.party import Party
from app.models.tenant import BusinessProfile
from app.pipeline import build_pipeline

# Transient job state — the counts come from the DB, this only carries what the
# database cannot know: that a run is in flight, and why it stopped.
_RUNS: dict[uuid.UUID, dict[str, Any]] = {}

PARTY_HINT_LIMIT = 40


def _party_hints(db, tenant_id: uuid.UUID) -> list[str]:
    """Grounding for the Extractor: real customer names beat a blank prompt."""
    rows = db.execute(
        select(Party.name).where(Party.tenant_id == tenant_id).limit(PARTY_HINT_LIMIT)
    ).scalars().all()
    return list(rows)


def _pending(db, tenant_id: uuid.UUID, job_id: uuid.UUID | None) -> list[Interaction]:
    """Interactions in this job the pipeline has not reached yet.

    Progress is marked on the interaction rather than inferred from whether an
    Extraction exists, because a message classified as noise correctly produces
    no Extraction at all — inferring would re-extract every "good morning ji"
    on each retry, at one model call apiece.

    Resuming a half-finished job is the same query as starting a fresh one,
    which is what makes a retry after a crash safe.
    """
    where = [
        Interaction.tenant_id == tenant_id,
        Interaction.attributes["outcome"].astext.is_(None),
    ]
    # No job id means everything still pending — onboarding backfills whatever
    # was uploaded before the profile existed.
    if job_id is not None:
        where.append(Interaction.attributes["job_id"].astext == str(job_id))

    return db.execute(
        select(Interaction).where(*where).order_by(Interaction.occurred_at.asc())
    ).scalars().all()


def run_backfill(tenant_id: uuid.UUID, job_id: uuid.UUID | None = None) -> None:
    """Push every pending interaction in the job through extract → apply.

    With no job id, everything still pending for the tenant is processed.
    """
    _RUNS[job_id] = {
        "tenant_id": tenant_id,
        "state": "running",
        "errors": [],
        "started_at": datetime.utcnow(),
    }

    try:
        with tenant_session(tenant_id) as db:
            profile = db.execute(
                select(BusinessProfile).where(BusinessProfile.tenant_id == tenant_id)
            ).scalars().first()

            graph = build_pipeline(db, tenant_id, profile)
            hints = _party_hints(db, tenant_id)

            for interaction in _pending(db, tenant_id, job_id):
                state = {
                    "trace_id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "interaction": {
                        "id": interaction.id,
                        "channel": interaction.channel,
                        "body": interaction.body or "",
                        "sender": interaction.sender,
                        "sender_phone": interaction.sender_phone,
                        "occurred_at": interaction.occurred_at,
                        "media_uri": interaction.media_uri,
                        "media_kind": interaction.media_kind,
                        "party_hints": hints,
                    },
                }
                try:
                    final = graph.invoke(state)
                    outcome = (final.get("result") or {}).get("status") or "processed"
                    # Reassigned, not mutated — SQLAlchemy only notices JSONB
                    # changes on assignment. Left unset on failure, so a retry
                    # picks the message up again.
                    interaction.attributes = {**(interaction.attributes or {}),
                                              "outcome": outcome}
                    # Per message, so one bad line cannot cost the whole export.
                    db.commit()
                except Exception as exc:  # noqa: BLE001 - one message must not stop the batch
                    db.rollback()
                    _RUNS[job_id]["errors"].append(f"{interaction.id}: {type(exc).__name__}: {exc}")

        _RUNS[job_id]["state"] = "done"
    except Exception as exc:  # noqa: BLE001 - surfaced through the job endpoint
        _RUNS[job_id]["state"] = "failed"
        _RUNS[job_id]["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        _RUNS[job_id]["finished_at"] = datetime.utcnow()


def job_status(db, tenant_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
    """Counts straight from the interactions the job created."""
    in_job = [
        Interaction.tenant_id == tenant_id,
        Interaction.attributes["job_id"].astext == str(job_id),
    ]

    total = db.execute(select(func.count()).select_from(Interaction).where(*in_job)).scalar_one()

    # One expression object, reused: writing it twice emits two bind params and
    # Postgres then refuses to accept it as a GROUP BY target.
    outcome = Interaction.attributes["outcome"].astext.label("outcome")
    by_outcome = dict(
        db.execute(select(outcome, func.count()).where(*in_job).group_by(outcome)).all()
    )
    processed = sum(count for outcome, count in by_outcome.items() if outcome is not None)

    # Only trust the in-memory run if it belongs to this tenant — the registry
    # is process-wide and its errors are not something to hand to a stranger.
    run = _RUNS.get(job_id) or {}
    if run.get("tenant_id") != tenant_id:
        run = {}

    state = run.get("state")
    if state is None:
        # Lost the in-memory run (restart, or another instance owns it).
        state = "done" if total and processed >= total else "unknown"

    return {
        "job_id": job_id,
        "state": state,
        "total": total,
        "processed": processed,
        "committed": by_outcome.get("committed", 0),
        "needs_review": by_outcome.get("needs_review", 0),
        "discarded": by_outcome.get("discarded", 0),
        "logged": by_outcome.get("logged", 0),
        "errors": run.get("errors", [])[:20],
    }
