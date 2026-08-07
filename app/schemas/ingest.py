"""Request/response shapes for ingestion."""

from __future__ import annotations

import uuid

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
    state: str  # queued | running | done | failed | unknown
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
