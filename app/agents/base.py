"""Agent base class.

Every agent inherits from this so that logging is impossible to forget. If an
agent decision isn't in `agent_run`, it didn't happen — that table is both the
debugging surface and the submission evidence.

Design note: agents return a Decision, never write to business tables directly.
Commits go through app/services/commit.py, which enforces the confidence
threshold and the review queue.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.observability import AgentRun
from app.models.tenant import BusinessProfile


@dataclass
class Decision:
    """What an agent concluded."""

    output: dict[str, Any]
    confidence: float
    rationale: str = ""
    escalate: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


class Agent:
    name: str = "unnamed"
    prompt_version: str = "v1"
    model: str = "gemini-2.5-flash"

    def __init__(self, db: Session, tenant_id: uuid.UUID, profile: BusinessProfile | None = None):
        self.db = db
        self.tenant_id = tenant_id
        self.profile = profile

    # --- subclasses implement this -------------------------------------
    def run(self, payload: dict[str, Any]) -> Decision:
        raise NotImplementedError

    # --- everything below is shared machinery --------------------------
    def execute(self, payload: dict[str, Any], trace_id: uuid.UUID | None = None) -> Decision:
        trace_id = trace_id or uuid.uuid4()
        started = time.perf_counter()
        error = None
        decision = None

        try:
            decision = self.run(payload)
        except Exception as exc:  # noqa: BLE001 - we want the log row either way
            error = f"{type(exc).__name__}: {exc}"
            decision = Decision(output={}, confidence=0.0, rationale="failed", escalate=True)
            raise
        finally:
            self._log(
                trace_id=trace_id,
                payload=payload,
                decision=decision,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )

        return decision

    def _log(self, *, trace_id, payload, decision, latency_ms, error) -> None:
        usage = (decision.meta.get("usage") if decision else {}) or {}
        row = AgentRun(
            tenant_id=self.tenant_id,
            trace_id=trace_id,
            agent=self.name,
            model=self.model,
            prompt_version=self.prompt_version,
            input_summary=str(payload)[:2000],
            input_hash=hashlib.sha256(repr(payload).encode()).hexdigest()[:64],
            decision=(decision.output if decision else {}),
            rationale=(decision.rationale if decision else ""),
            confidence=(decision.confidence if decision else 0.0),
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cost_usd=usage.get("cost_usd"),
            outcome="error" if error else ("escalated" if decision and decision.escalate else "ok"),
            error=error,
        )
        self.db.add(row)
        self.db.flush()
