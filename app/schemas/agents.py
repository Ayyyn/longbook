"""Response shapes for the Agent Activity feed.

This screen is two things at once: the owner's reason to trust the system, and
the evidence of AI-native operations the XPRIZE submission asks for. So it
reports the unflattering numbers too — override rate, errors, cost — rather
than only the runs that went well.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentRunOut(BaseModel):
    id: uuid.UUID
    trace_id: uuid.UUID | None
    agent: str | None
    model: str | None
    prompt_version: str | None

    decision: dict[str, Any] = Field(default_factory=dict)
    rationale: str | None
    confidence: float | None

    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None

    outcome: str | None
    error: str | None
    human_override: bool
    reviewed_at: datetime | None
    created_at: datetime | None

    # What the run was actually about, so the feed reads as work and not as logs.
    subject: str | None = None
    record_type: str | None = None


class AgentFeed(BaseModel):
    items: list[AgentRunOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class AgentStat(BaseModel):
    agent: str
    runs: int
    ok: int
    errors: int
    escalated: int
    overrides: int
    override_rate: float
    avg_confidence: float | None
    avg_latency_ms: int | None
    cost_usd: float


class Throughput(BaseModel):
    """What the system actually did with the records it produced.

    Auto-commit rate alone understates the system once field-level gating is on:
    a record written with one blank to confirm counts as "review" but is very
    nearly done. `written_rate` and `fields_per_review_item` are what separate
    that from an empty form.
    """

    records: int = 0
    auto_committed: int = 0
    partially_committed: int = 0
    queued: int = 0
    auto_commit_rate: float = 0.0
    written_rate: float = 0.0
    review_rate: float = 0.0
    fields_per_review_item: float | None = None


class AgentSummary(BaseModel):
    since: datetime | None
    throughput: Throughput = Throughput()
    runs: int
    runs_today: int
    overrides: int
    override_rate: float
    errors: int
    error_rate: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: int | None
    by_agent: list[AgentStat] = Field(default_factory=list)


class TraceStep(BaseModel):
    agent: str | None
    outcome: str | None
    confidence: float | None
    rationale: str | None
    decision: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None
    created_at: datetime | None


class Trace(BaseModel):
    """One message's whole journey, which is the demo."""

    trace_id: uuid.UUID
    message: str | None
    sender: str | None
    occurred_at: datetime | None
    steps: list[TraceStep] = Field(default_factory=list)
    outcome: str | None = None
    record_type: str | None = None
    committed_id: uuid.UUID | None = None
    human_override: bool = False
