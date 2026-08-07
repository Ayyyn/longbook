"""Request/response shapes for the review queue.

Shaped for one screen used with one thumb: everything the owner needs to judge
an item is in the list payload, so accepting does not cost a round trip.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SourceMessage(BaseModel):
    """One line of the conversation behind a record."""

    id: uuid.UUID
    sender: str | None
    occurred_at: datetime | None
    body: str | None
    cited: bool = False  # the model said this record came from this line


class ValidationResult(BaseModel):
    rule: str
    status: str  # pass | fail | not_applicable
    detail: str = ""
    fields: list[str] = []


class QueueItem(BaseModel):
    extraction_id: uuid.UUID
    trace_id: uuid.UUID | None = None  # joins to agent_run
    record_type: str | None
    confidence: float | None
    reason: str | None
    flags: list[str] = []

    fields: dict[str, Any] = {}
    # Field-level gating: everything else on this record is already committed.
    # These are the only things the owner is being asked about.
    pending_fields: list[str] = []
    pending_reasons: dict[str, str] = {}
    validations: list[ValidationResult] = []
    committed_type: str | None = None
    committed_id: uuid.UUID | None = None

    party_id: uuid.UUID | None = None
    party_name: str | None = None
    party_candidates: list[dict[str, Any]] = []
    suggest_create: str | None = None

    # The conversation this record was drawn from, so the owner judges the
    # source rather than our guess. `message` is the flattened form the card
    # shows; `conversation` is the line-by-line detail.
    message: str | None = None
    conversation: list[SourceMessage] = []
    sender: str | None = None
    occurred_at: datetime | None = None
    created_at: datetime | None = None


class QueuePage(BaseModel):
    items: list[QueueItem]
    total: int
    limit: int
    offset: int


class Correction(BaseModel):
    """Everything is optional — omitted fields keep what the agent proposed."""

    record_type: str | None = None
    fields: dict[str, Any] | None = None
    party_id: uuid.UUID | None = None
    party_name: str | None = None


class Rejection(BaseModel):
    reason: str | None = None


class ReviewResult(BaseModel):
    extraction_id: uuid.UUID
    status: str
    record_type: str | None = None
    id: str | None = None
    flags: list[str] = []
