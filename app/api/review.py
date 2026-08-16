"""Review queue routes.

The screen these serve is the one the owner touches every day, so the list
endpoint returns everything needed to judge an item — the original message, the
extracted fields, why the agent hesitated, and any party candidates. Accepting
is then a single tap with no second round trip.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import TenantDB, TenantId
from app.models.ingestion import Extraction, Interaction
from app.models.party import Party
from app.schemas.review import (
    Correction,
    QueueItem,
    QueuePage,
    Rejection,
    ReviewResult,
    SourceMessage,
    ValidationResult,
)
from app.services.commit import accept_correction

router = APIRouter()

REVIEWABLE = "needs_review"


def _conversation(db, extraction: Extraction) -> list[SourceMessage]:
    """The window this record came from, with the cited lines marked.

    The owner is confirming a record drawn from a conversation, so they need
    the conversation — not just the one message the extraction happens to be
    anchored to.
    """
    cited = {str(i) for i in (extraction.source_message_ids or [])}

    rows: list[Interaction] = []
    if extraction.window_id:
        rows = db.execute(
            select(Interaction)
            .where(Interaction.window_id == extraction.window_id)
            .order_by(Interaction.occurred_at.asc().nullslast(), Interaction.id.asc())
        ).scalars().all()
    elif extraction.interaction_id:
        one = db.get(Interaction, extraction.interaction_id)
        rows = [one] if one else []

    return [
        SourceMessage(
            id=row.id,
            sender=row.sender,
            occurred_at=row.occurred_at,
            body=row.body,
            cited=str(row.id) in cited,
        )
        for row in rows
    ]


def _candidates(raw, db) -> list[dict]:
    """Normalise the Resolver's ambiguous-party shortlist.

    The Resolver used to store bare uuid strings here. Rows written before
    that changed are still in the database and still in the queue, and a
    schema mismatch must not take the whole review screen down with a 500 —
    so old rows get their names looked up rather than rejected.
    """
    out: list[dict] = []
    for item in raw or []:
        if isinstance(item, dict):
            out.append(item)
            continue
        party = db.get(Party, uuid.UUID(str(item))) if item else None
        if party:
            out.append({"id": str(party.id), "name": party.name, "score": None})
    return out


def _to_item(
    db,
    extraction: Extraction,
    interaction: Interaction | None,
    party: Party | None,
    conversation: list[SourceMessage] | None = None,
) -> QueueItem:
    resolved = extraction.resolved or {}
    conversation = conversation or []
    # Prefer the lines the model actually cited; fall back to the whole window
    # so the card is never blank.
    quoted = [m for m in conversation if m.cited] or conversation
    flattened = "\n".join(f"{m.sender}: {m.body}" for m in quoted if m.body) or None
    return QueueItem(
        extraction_id=extraction.id,
        trace_id=extraction.trace_id,
        record_type=extraction.record_type,
        confidence=float(extraction.confidence) if extraction.confidence is not None else None,
        reason=extraction.reason,
        flags=resolved.get("flags", []),
        fields=extraction.payload or {},
        pending_fields=list(extraction.pending_fields or []),
        pending_reasons=(extraction.resolved or {}).get("pending_reasons", {}),
        validations=[
            ValidationResult(**v) for v in (extraction.validations or [])
            if isinstance(v, dict)
        ],
        committed_type=extraction.committed_type,
        committed_id=extraction.committed_id,
        party_id=party.id if party else None,
        party_name=party.name if party else None,
        party_candidates=_candidates(resolved.get("candidates", []), db),
        suggest_create=resolved.get("suggest_create"),
        message=flattened or (interaction.body if interaction else None),
        conversation=conversation,
        sender=(quoted[0].sender if quoted else (interaction.sender if interaction else None)),
        occurred_at=(
            quoted[-1].occurred_at if quoted
            else (interaction.occurred_at if interaction else None)
        ),
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
        items.append(_to_item(db, extraction, interaction, party, _conversation(db, extraction)))

    return QueuePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{extraction_id}", response_model=QueueItem)
def get_item(extraction_id: uuid.UUID, tid: TenantId, db: TenantDB) -> QueueItem:
    extraction = _load(db, tid, extraction_id)
    interaction = (
        db.get(Interaction, extraction.interaction_id) if extraction.interaction_id else None
    )
    pid = (extraction.resolved or {}).get("party_id")
    party = db.get(Party, uuid.UUID(str(pid))) if pid else None
    return _to_item(db, extraction, interaction, party, _conversation(db, extraction))


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


class MergeSuggestionOut(BaseModel):
    suggestion_id: str
    primary_id: uuid.UUID
    duplicate_id: uuid.UUID
    primary_name: str
    duplicate_name: str
    reason: str
    confidence: float
    primary_records: int
    duplicate_records: int


class MergeDecision(BaseModel):
    primary_id: uuid.UUID
    duplicate_id: uuid.UUID


@router.get("/merges", response_model=list[MergeSuggestionOut])
def merge_suggestions(tid: TenantId, db: TenantDB) -> list[MergeSuggestionOut]:
    """Parties that look like the same business written down twice.

    Suggestions only. Nothing here changes a record; the owner decides, because
    a wrong merge combines two customers' ledgers and cannot be undone.
    """
    from app.services.party_merge import suggest_merges

    return [
        MergeSuggestionOut(
            suggestion_id=s.suggestion_id,
            primary_id=s.primary_id, duplicate_id=s.duplicate_id,
            primary_name=s.primary_name, duplicate_name=s.duplicate_name,
            reason=s.reason, confidence=s.confidence,
            primary_records=s.primary_records, duplicate_records=s.duplicate_records,
        )
        for s in suggest_merges(db, tid)
    ]


@router.post("/merges/accept")
def accept_merge(payload: MergeDecision, tid: TenantId, db: TenantDB) -> dict:
    """Combine the two, keeping the duplicate's name as an alias."""
    from app.services.party_merge import merge_parties

    try:
        return merge_parties(db, tid, payload.primary_id, payload.duplicate_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/merges/reject")
def dismiss_merge(payload: MergeDecision, tid: TenantId, db: TenantDB) -> dict:
    """They are different businesses. Stop suggesting this pair."""
    from app.services.party_merge import reject_merge

    reject_merge(db, tid, payload.primary_id, payload.duplicate_id)
    return {"dismissed": True}
