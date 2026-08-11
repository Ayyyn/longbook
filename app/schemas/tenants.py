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
    # Where the close-of-business digest goes. The column has always been
    # here; without capturing it at creation the digest composes every
    # evening and silently has nowhere to send.
    owner_email: str | None = None
    city: str | None = None
    locale: str = Field(default="en", description="en | hi | gu | mr")


class TenantCreated(BaseModel):
    tenant_id: uuid.UUID
    business_name: str
    token: str
    owner_phone: str | None = None
    # Whether the token also went to their inbox. The signup screen changes
    # what it tells the owner to do based on this.
    emailed_to: str | None = None
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

    # Answers to the questions the Interviewer wrote for this business.
    # Free-form because the questions are: {question: answer}. They reach the
    # Configurator as prose, which is what it reads anyway — no schema is
    # invented from them and nothing is stored per-key.
    answers: dict[str, str] = Field(default_factory=dict)

    def render(self) -> str:
        """Flatten to the text the Configurator reads."""
        lines = [
            f"Segments the owner selected: {', '.join(self.segments) or 'not stated'}",
            f"What they sell: {self.what_you_sell or 'not stated'}",
            f"Units they quote in: {self.units or 'not stated'}",
            f"Tracks batches or lot numbers: {_yes_no(self.tracks_lots)}",
            f"Gives credit: {_yes_no(self.gives_credit)}",
            f"Typical credit days: {self.credit_days if self.credit_days is not None else 'not stated'}",
        ]
        # These were asked because the owner's own messages prompted them, so
        # they carry more signal than the fixed fields above and get their own
        # block rather than being flattened into notes.
        if self.answers:
            lines.append("What the owner said about their own business:")
            lines.extend(
                f"  {question} -> {answer}"
                for question, answer in self.answers.items()
                if str(answer).strip()
            )
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
    estimated_minutes: int = 0
    duplicates: int = 0


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
    # Thresholds the agent proposed that were clamped or rejected for want
    # of evidence, so the owner is told rather than silently overridden.
    rule_notes: list[str] = Field(default_factory=list)


class ConfigureResult(BaseModel):
    tenant_id: uuid.UUID
    profile: ProfileOut
    # Watch this to show records appearing as they are extracted.
    backfill_job_id: uuid.UUID
    pending_interactions: int
    parties: int
    parties_seeded_from: str | None = None
    detail: str


class TenantMe(BaseModel):
    tenant_id: uuid.UUID
    business_name: str
    owner_name: str | None
    owner_phone: str
    owner_email: str | None
    city: str | None
    locale: str
    onboarded_at: datetime | None
    # trial | active | expired, with the countdown the app shows near expiry.
    access_status: str = "active"
    days_remaining: int | None = None
    paid_until: datetime | None = None
    plan: str | None = None
    # What this business calls things, resolved from its profile. The UI
    # renders these rather than guessing at a trade.
    labels: dict[str, Any] = Field(default_factory=dict)
    profile: ProfileOut | None
    parties: int
    interactions: int
    needs_review: int


class PaymentRecord(BaseModel):
    """Payment is taken in person and marked here. There is no gateway."""

    paid_until: datetime
    plan: str | None = None
    note: str | None = None


class PaymentRecorded(BaseModel):
    tenant_id: uuid.UUID
    business_name: str
    plan: str | None
    paid_until: datetime
    access_status: str
    days_remaining: int | None


class TenantSummary(BaseModel):
    """What an operator needs on the phone to find the right business."""

    tenant_id: uuid.UUID
    business_name: str
    owner_name: str | None
    owner_phone: str
    owner_email: str | None
    city: str | None
    access_status: str
    days_remaining: int | None
    paid_until: datetime | None


class RecoveryRequest(BaseModel):
    phone: str


class RecoveryAccepted(BaseModel):
    """Deliberately says the same thing whether or not the business exists."""

    detail: str = (
        "If that number belongs to a business with an email on file, we have "
        "sent a link to it."
    )


class RecoveryConfirm(BaseModel):
    token_payload: str


class Question(BaseModel):
    key: str
    purpose: str
    type: str            # text | bool | number | choice
    question: str
    hint: str = ""
    options: list[str] = []


class InterviewQuestions(BaseModel):
    questions: list[Question]
    # False when the neutral fallback set was used — the UI says nothing
    # different, but it matters when reading the logs.
    generated: bool
    observations: list[str] = []
