"""LangGraph ingestion pipeline.

    interaction -> extract -> resolve -> triage -> commit | review

Kept as one linear graph on purpose. The branching that matters (auto-commit
vs review) is a single decision node, and every hop writes an agent_run row
carrying the same trace_id so a record's whole history is one query.
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agents import Extractor, Resolver, Triage
from app.services.commit import commit_record, queue_for_review


class PipelineState(TypedDict, total=False):
    trace_id: uuid.UUID
    tenant_id: uuid.UUID
    interaction: dict[str, Any]
    extraction: dict[str, Any]
    resolution: dict[str, Any]
    action: str
    # Triage's reasons, carried to the review queue. Keys absent from this
    # schema are dropped by LangGraph rather than passed along.
    flags: list[str]
    result: dict[str, Any]


def build_pipeline(db, tenant_id, profile):
    ex = Extractor(db, tenant_id, profile)
    rs = Resolver(db, tenant_id, profile)
    tr = Triage(db, tenant_id, profile)

    def n_extract(state: PipelineState) -> PipelineState:
        d = ex.execute(state["interaction"], trace_id=state["trace_id"])
        return {**state, "extraction": {**d.output, "confidence": d.confidence,
                                        "reason": d.rationale}}

    def n_resolve(state: PipelineState) -> PipelineState:
        if state["extraction"].get("record_type") == "noise":
            return {**state, "resolution": {}, "action": "discard"}
        payload = {**state["extraction"],
                   "sender_phone": state["interaction"].get("sender_phone")}
        d = rs.execute(payload, trace_id=state["trace_id"])
        return {**state, "resolution": {**d.output, "confidence": d.confidence}}

    def n_triage(state: PipelineState) -> PipelineState:
        if state.get("action") == "discard":
            return state
        payload = {
            "record_type": state["extraction"].get("record_type"),
            "confidence": min(state["extraction"].get("confidence", 0),
                              state["resolution"].get("confidence", 1)),
            "party_id": state["resolution"].get("party_id"),
            **state["extraction"].get("fields", {}),
        }
        d = tr.execute(payload, trace_id=state["trace_id"])
        # Carry the flags, not just the verdict: they are what the review
        # screen shows the owner as the reason this item is in front of them.
        return {
            **state,
            "action": d.output.get("action", "review"),
            "flags": d.output.get("flags", []),
        }

    def n_apply(state: PipelineState) -> PipelineState:
        action = state.get("action")
        if action == "commit":
            return {**state, "result": commit_record(db, state)}
        if action == "review":
            return {**state, "result": queue_for_review(db, state)}
        return {**state, "result": {"status": "discarded"}}

    g = StateGraph(PipelineState)
    g.add_node("extract", n_extract)
    g.add_node("resolve", n_resolve)
    g.add_node("triage", n_triage)
    g.add_node("apply", n_apply)
    g.set_entry_point("extract")
    g.add_edge("extract", "resolve")
    g.add_edge("resolve", "triage")
    g.add_edge("triage", "apply")
    g.add_edge("apply", END)
    return g.compile()
