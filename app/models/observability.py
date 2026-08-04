"""Agent run log.

This table is load-bearing for two reasons: it is how you debug extraction
failures on day 9, and it is the evidence of AI-native operations that the
XPRIZE submission asks for. Write it synchronously; stream to BigQuery async.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base, TenantScoped


class AgentRun(Base, TenantScoped):
    __tablename__ = "agent_run"

    trace_id = Column(UUID(as_uuid=True), index=True)
    agent = Column(String(48), index=True)      # configurator|extractor|resolver|...
    model = Column(String(48))
    prompt_version = Column(String(24))

    input_summary = Column(Text)
    input_hash = Column(String(64), index=True)

    decision = Column(JSONB, default=dict)      # what it chose, structured
    rationale = Column(Text)                    # short natural-language why
    confidence = Column(Numeric(4, 3))

    latency_ms = Column(Integer)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cost_usd = Column(Numeric(10, 6))

    outcome = Column(String(24))                # ok | error | escalated
    error = Column(Text, nullable=True)
    human_override = Column(Boolean, default=False)
    reviewed_at = Column(DateTime, nullable=True)
