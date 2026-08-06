"""Request/response shapes for onboarding.

The interview is short by design: the whole flow happens with the owner sitting
across the table, and anything that cannot be answered in a sentence belongs in
the message sample instead, where the Configurator can infer it from evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TenantCreate(BaseModel):
    business_name: str
    owner_phone: str
    owner_name: str | None = None
    city: str | None = None
    locale: str = Field(default="en", description="en | hi | gu | mr")


class TenantCreated(BaseModel):
    tenant_id: uuid.UUID
    business_name: str
    token: str
    detail: str = "Store this token now — it is not shown again."


class Interview(BaseModel):
    """Answers the owner gives out loud while the export uploads."""

    segments: list[str] = Field(default_factory=list, description="wholesaler and/or retail")
    what_you_sell: str | None = None
    units: str | None = Field(default=None, description="e.g. 'meter, thaan'")
    tracks_lots: bool | None = None
    gives_credit: bool | None = None
    credit_days: int | None = None
    notes: str | None = None

    def render(self) -> str:
        """Flatten to the text the Configurator reads."""
        lines = [
            f"Segments the owner selected: {', '.join(self.segments) or 'not stated'}",
            f"What they sell: {self.what_you_sell or 'not stated'}",
            f"Units they quote in: {self.units or 'not stated'}",
            f"Tracks dye lots: {_yes_no(self.tracks_lots)}",
            f"Gives credit: {_yes_no(self.gives_credit)}",
            f"Typical credit days: {self.credit_days if self.credit_days is not None else 'not stated'}",
        ]
        if self.notes:
            lines.append(f"Other notes: {self.notes}")
        return "\n".join(lines)


def _yes_no(value: bool | None) -> str:
    return "not stated" if value is None else ("yes" if value else "no")


class SampleAccepted(BaseModel):
    job_id: uuid.UUID
    interactions: int
    skipped: int
    kind: str
    preview: list[str] = Field(default_factory=list, description="First few messages, verbatim")
    detail: str


class PartyImportResult(BaseModel):
    source: str  # tally | excel | messages
    created: int
    merged: int
    skipped: int
    opening_invoices: int
    total_outstanding: float
    parties_total: int
    preview: list[str] = Field(default_factory=list)
    detail: str


class ProfileOut(BaseModel):
    segments: list[str]
    modules: dict[str, Any]
    vocabulary: dict[str, Any]
    rules: dict[str, Any]
    version: str
    source: str  # configurator | seed
    confidence: float | None = None
    rationale: str | None = None


class ConfigureResult(BaseModel):
    tenant_id: uuid.UUID
    profile: ProfileOut
    pending_interactions: int
    parties: int
    parties_seeded_from: str | None = None
    detail: str


class TenantMe(BaseModel):
    tenant_id: uuid.UUID
    business_name: str
    owner_name: str | None
    owner_phone: str
    city: str | None
    locale: str
    onboarded_at: datetime | None
    profile: ProfileOut | None
    parties: int
    interactions: int
    needs_review: int
