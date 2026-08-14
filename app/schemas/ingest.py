"""Request/response shapes for ingestion."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class IngestAccepted(BaseModel):
    """Returned immediately; the pipeline runs behind it."""

    job_id: uuid.UUID
    interactions: int
    skipped: int
    kind: str  # whatsapp_export | excel | image
    detail: str


class JobStatus(BaseModel):
    job_id: uuid.UUID
    # setup_required: messages are held but nothing can read them until
    # the interview is answered and a profile exists.
    state: str  # queued | running | done | failed | unknown | setup_required
    total: int
    processed: int
    # Conversation windows, which is what the backfill actually works
    # through — the owner watches this move during onboarding.
    windows_total: int = 0
    windows_done: int = 0
    committed: int
    needs_review: int
    discarded: int
    logged: int = 0  # enquiries — context, not a business record
    errors: list[str] = []


class FileEstimateOut(BaseModel):
    filename: str
    kind: str
    messages: int
    duplicates: int
    skipped: int
    media: int
    bytes: int
    error: str | None = None


class EstimateOut(BaseModel):
    """What an upload would do, before the owner commits to it."""

    files: list[FileEstimateOut]
    new_messages: int
    duplicates: int
    media: int
    estimated_minutes: int
    detail: str


class SourceOut(BaseModel):
    id: uuid.UUID
    kind: str
    label: str | None
    messages: int
    duplicates: int
    media: int
    status: str
    detail: str | None
    created_at: datetime
