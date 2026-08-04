"""Request/response shapes for the review queue.

Shaped for one screen used with one thumb: everything the owner needs to judge
an item is in the list payload, so accepting does not cost a round trip.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class QueueItem(BaseModel):
    extraction_id: uuid.UUID
    record_type: str | None
    confidence: float | None
    reason: str | None
    flags: list[str] = []

    fields: dict[str, Any] = {}
    party_id: uuid.UUID | None = None
    party_name: str | None = None
    party_candidates: list[dict[str, Any]] = []
    suggest_create: str | None = None

    # The original message, so the owner judges the source, not our guess.
    message: str | None = None
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
