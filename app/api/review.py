"""Review queue routes.

The screen these serve is the one the owner touches every day, so the list
endpoint returns everything needed to judge an item — the original message, the
extracted fields, why the agent hesitated, and any party candidates. Accepting
is then a single tap with no second round trip.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import TenantDB, TenantId
from app.models.ingestion import Extraction, Interaction
from app.models.party import Party
from app.schemas.review import Correction, QueueItem, QueuePage, Rejection, ReviewResult
from app.services.commit import accept_correction

router = APIRouter()

REVIEWABLE = "needs_review"


def _to_item(
    extraction: Extraction, interaction: Interaction | None, party: Party | None
) -> QueueItem:
    resolved = extraction.resolved or {}
    return QueueItem(
        extraction_id=extraction.id,
        record_type=extraction.record_type,
        confidence=float(extraction.confidence) if extraction.confidence is not None else None,
        reason=extraction.reason,
        flags=resolved.get("flags", []),
        fields=extraction.payload or {},
        party_id=party.id if party else None,
        party_name=party.name if party else None,
        party_candidates=resolved.get("candidates", []),
        suggest_create=resolved.get("suggest_create"),
        message=interaction.body if interaction else None,
        sender=interaction.sender if interaction else None,
        occurred_at=interaction.occurred_at if interaction else None,
        created_at=extraction.created_at,
    )


def _load(db, tid: uuid.UUID, extraction_id: uuid.UUID) -> Extraction:
    extraction = db.execute(
        select(Extraction).where(Extraction.tenant_id == tid, Extraction.id == extraction_id)
    ).scalars().first()
    if extraction is None:
        raise HTTPException(404, f"Extraction {extraction_id} not found.")
    return extraction


def _assert_open(extraction: Extraction) -> None:
    if extraction.status != REVIEWABLE:
        raise HTTPException(409, f"Extraction is already '{extraction.status}'.")


def _result_payload(result: dict) -> dict:
    return {
        "extraction_id": uuid.UUID(result["extraction_id"]),
        "status": result.get("status", "accepted"),
        "record_type": result.get("record_type"),
        "id": result.get("id"),
        "flags": result.get("flags", []),
    }


@router.get("/queue", response_model=QueuePage)
def list_queue(
    tid: TenantId,
    db: TenantDB,
    record_type: str | None = Query(None, description="order | payment | dispatch"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> QueuePage:
    """Oldest first — the queue is worked front to back, not newest-first."""
    where = [Extraction.tenant_id == tid, Extraction.status == REVIEWABLE]
    if record_type:
        where.append(Extraction.record_type == record_type)

    total = db.execute(select(func.count()).select_from(Extraction).where(*where)).scalar_one()

    rows = db.execute(
        select(Extraction, Interaction)
        .outerjoin(Interaction, Interaction.id == Extraction.interaction_id)
        .where(*where)
        .order_by(Extraction.created_at.asc())
        .limit(limit)
        .offset(offset)
    ).all()

    # One lookup for every party mentioned, rather than one per row.
    party_ids = {
        uuid.UUID(str(pid))
        for extraction, _ in rows
        if (pid := (extraction.resolved or {}).get("party_id"))
    }
    parties = {}
    if party_ids:
        parties = {
            p.id: p
            for p in db.execute(
                select(Party).where(Party.tenant_id == tid, Party.id.in_(party_ids))
            ).scalars().all()
        }

    items = []
    for extraction, interaction in rows:
        pid = (extraction.resolved or {}).get("party_id")
        party = parties.get(uuid.UUID(str(pid))) if pid else None
        items.append(_to_item(extraction, interaction, party))

    return QueuePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{extraction_id}", response_model=QueueItem)
def get_item(extraction_id: uuid.UUID, tid: TenantId, db: TenantDB) -> QueueItem:
    extraction = _load(db, tid, extraction_id)
    interaction = (
        db.get(Interaction, extraction.interaction_id) if extraction.interaction_id else None
    )
    pid = (extraction.resolved or {}).get("party_id")
    party = db.get(Party, uuid.UUID(str(pid))) if pid else None
    return _to_item(extraction, interaction, party)


@router.post("/{extraction_id}/accept", response_model=ReviewResult)
def accept(extraction_id: uuid.UUID, tid: TenantId, db: TenantDB) -> ReviewResult:
    """Commit the agent's proposal unchanged."""
    extraction = _load(db, tid, extraction_id)
    _assert_open(extraction)
    result = accept_correction(db, extraction.id, {})
    return ReviewResult(**_result_payload(result))


@router.post("/{extraction_id}/correct", response_model=ReviewResult)
def correct(
    extraction_id: uuid.UUID, correction: Correction, tid: TenantId, db: TenantDB
) -> ReviewResult:
    """Commit the owner's version and harvest it as a few-shot example."""
    extraction = _load(db, tid, extraction_id)
    _assert_open(extraction)

    result = accept_correction(db, extraction.id, correction.model_dump(exclude_none=True))
    return ReviewResult(**_result_payload(result))


@router.post("/{extraction_id}/reject", response_model=ReviewResult)
def reject(
    extraction_id: uuid.UUID, rejection: Rejection, tid: TenantId, db: TenantDB
) -> ReviewResult:
    """Not a business record. Nothing is written; the extraction keeps the why."""
    extraction = _load(db, tid, extraction_id)
    _assert_open(extraction)

    extraction.status = "rejected"
    if rejection.reason:
        extraction.reason = rejection.reason
    db.flush()

    return ReviewResult(
        extraction_id=extraction.id, status="rejected", record_type=extraction.record_type
    )
