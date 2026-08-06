"""Agent Activity: what the agents decided, how sure they were, and how often
the owner disagreed.

Two audiences, one endpoint set. The owner needs to see the system working on
their own data before they trust it with their ledger. The XPRIZE submission
needs the same rows as evidence. Both are better served by numbers that
include the failures, so error and override rates are first-class here rather
than buried.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import Integer, func, select

from app.api.deps import TenantDB, TenantId
from app.models.ingestion import Extraction, Interaction
from app.models.observability import AgentRun
from app.schemas.agents import (
    AgentFeed,
    AgentRunOut,
    AgentStat,
    AgentSummary,
    Trace,
    TraceStep,
)

router = APIRouter()

# The order a message actually moves through, so a trace reads top to bottom
# even when two runs share a timestamp.
STEP_ORDER = {"extractor": 0, "resolver": 1, "triage": 2, "ledger_analyst": 3,
              "digest_composer": 4, "draft_composer": 5, "configurator": -1}


def _float(value) -> float | None:
    return float(value) if value is not None else None


def _since(days: int | None) -> datetime | None:
    return datetime.utcnow() - timedelta(days=days) if days else None


@router.get("/runs", response_model=AgentFeed)
def feed(
    tid: TenantId,
    db: TenantDB,
    agent: str | None = Query(None),
    outcome: str | None = Query(None, description="ok | error | escalated"),
    overrides_only: bool = Query(False),
    days: int | None = Query(None, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AgentFeed:
    """Newest first — this one is watched live during a demo."""
    where = [AgentRun.tenant_id == tid]
    if agent:
        where.append(AgentRun.agent == agent)
    if outcome:
        where.append(AgentRun.outcome == outcome)
    if overrides_only:
        where.append(AgentRun.human_override.is_(True))
    since = _since(days)
    if since:
        where.append(AgentRun.created_at >= since)

    total = db.execute(select(func.count()).select_from(AgentRun).where(*where)).scalar_one()

    rows = db.execute(
        select(AgentRun, Interaction.body, Extraction.record_type)
        .outerjoin(Extraction, Extraction.trace_id == AgentRun.trace_id)
        .outerjoin(Interaction, Interaction.id == Extraction.interaction_id)
        .where(*where)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return AgentFeed(
        items=[
            AgentRunOut(
                id=run.id,
                trace_id=run.trace_id,
                agent=run.agent,
                model=run.model,
                prompt_version=run.prompt_version,
                decision=run.decision or {},
                rationale=run.rationale,
                confidence=_float(run.confidence),
                latency_ms=run.latency_ms,
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
                cost_usd=_float(run.cost_usd),
                outcome=run.outcome,
                error=run.error,
                human_override=bool(run.human_override),
                reviewed_at=run.reviewed_at,
                created_at=run.created_at,
                subject=(body or "")[:200] or None,
                record_type=record_type,
            )
            for run, body, record_type in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=AgentSummary)
def summary(
    tid: TenantId,
    db: TenantDB,
    days: int | None = Query(30, ge=1, le=365),
) -> AgentSummary:
    """Headline reliability and cost numbers."""
    where = [AgentRun.tenant_id == tid]
    since = _since(days)
    if since:
        where.append(AgentRun.created_at >= since)

    rows = db.execute(
        select(
            AgentRun.agent,
            func.count(),
            func.sum(func.cast(AgentRun.outcome == "ok", Integer)),
            func.sum(func.cast(AgentRun.outcome == "error", Integer)),
            func.sum(func.cast(AgentRun.outcome == "escalated", Integer)),
            func.sum(func.cast(AgentRun.human_override, Integer)),
            func.avg(AgentRun.confidence),
            func.avg(AgentRun.latency_ms),
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.coalesce(func.sum(AgentRun.input_tokens), 0),
            func.coalesce(func.sum(AgentRun.output_tokens), 0),
        )
        .where(*where)
        .group_by(AgentRun.agent)
        .order_by(func.count().desc())
    ).all()

    by_agent = []
    runs = overrides = errors = input_tokens = output_tokens = 0
    cost = 0.0
    latency_weighted = 0.0

    for (name, count, ok_count, error_count, escalated, override_count,
         avg_conf, avg_latency, agent_cost, tokens_in, tokens_out) in rows:
        runs += count
        overrides += int(override_count or 0)
        errors += int(error_count or 0)
        cost += float(agent_cost or 0)
        input_tokens += int(tokens_in or 0)
        output_tokens += int(tokens_out or 0)
        if avg_latency:
            latency_weighted += float(avg_latency) * count

        by_agent.append(
            AgentStat(
                agent=name or "unknown",
                runs=count,
                ok=int(ok_count or 0),
                errors=int(error_count or 0),
                escalated=int(escalated or 0),
                overrides=int(override_count or 0),
                override_rate=round(int(override_count or 0) / count, 4) if count else 0.0,
                avg_confidence=round(float(avg_conf), 3) if avg_conf is not None else None,
                avg_latency_ms=int(avg_latency) if avg_latency is not None else None,
                cost_usd=round(float(agent_cost or 0), 6),
            )
        )

    today_count = db.execute(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.tenant_id == tid, func.date(AgentRun.created_at) == date.today())
    ).scalar_one()

    return AgentSummary(
        since=since,
        runs=runs,
        runs_today=today_count,
        overrides=overrides,
        override_rate=round(overrides / runs, 4) if runs else 0.0,
        errors=errors,
        error_rate=round(errors / runs, 4) if runs else 0.0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        avg_latency_ms=int(latency_weighted / runs) if runs else None,
        by_agent=by_agent,
    )


@router.get("/trace/{trace_id}", response_model=Trace)
def trace(trace_id: uuid.UUID, tid: TenantId, db: TenantDB) -> Trace:
    """One message's whole journey: extract, resolve, triage, and what it became."""
    runs = db.execute(
        select(AgentRun)
        .where(AgentRun.tenant_id == tid, AgentRun.trace_id == trace_id)
        .order_by(AgentRun.created_at.asc())
    ).scalars().all()
    if not runs:
        raise HTTPException(404, f"No agent runs for trace {trace_id}.")

    extraction = db.execute(
        select(Extraction).where(Extraction.tenant_id == tid, Extraction.trace_id == trace_id)
    ).scalars().first()

    interaction = None
    if extraction and extraction.interaction_id:
        interaction = db.get(Interaction, extraction.interaction_id)

    ordered = sorted(runs, key=lambda r: (STEP_ORDER.get(r.agent or "", 99), r.created_at))

    return Trace(
        trace_id=trace_id,
        message=interaction.body if interaction else None,
        sender=interaction.sender if interaction else None,
        occurred_at=interaction.occurred_at if interaction else None,
        steps=[
            TraceStep(
                agent=run.agent,
                outcome=run.outcome,
                confidence=_float(run.confidence),
                rationale=run.rationale,
                decision=run.decision or {},
                latency_ms=run.latency_ms,
                created_at=run.created_at,
            )
            for run in ordered
        ],
        outcome=extraction.status if extraction else None,
        record_type=extraction.record_type if extraction else None,
        committed_id=extraction.committed_id if extraction else None,
        human_override=any(bool(run.human_override) for run in runs),
    )
