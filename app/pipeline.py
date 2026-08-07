"""LangGraph ingestion pipeline.

    window -> extract -> resolve -> triage -> commit | review

The unit is a conversation window, not a message: an order is built across
several lines, and asking for confidence on one line in isolation is asking
for a guess. One window can yield several records — an order and the payment
for it — so extract fans out and the later nodes work over a list.

Kept as one linear graph on purpose. The branching that matters (auto-commit
vs review) is a single decision per record, and every hop writes an agent_run
row carrying the same trace_id so a window's whole history is one query.
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
    window: dict[str, Any]
    # One entry per record the window yielded. Keys absent from this schema
    # are dropped by LangGraph rather than passed along.
    records: list[dict[str, Any]]
    results: list[dict[str, Any]]


def build_pipeline(db, tenant_id, profile):
    ex = Extractor(db, tenant_id, profile)
    rs = Resolver(db, tenant_id, profile)
    tr = Triage(db, tenant_id, profile)

    def n_extract(state: PipelineState) -> PipelineState:
        window = state["window"]
        d = ex.execute(
            {
                "body": window["text"],
                "party_hints": window.get("party_hints", []),
                "message_count": window.get("message_count", 0),
                "media_uri": window.get("media_uri"),
                "media_kind": window.get("media_kind"),
            },
            trace_id=state["trace_id"],
        )
        return {**state, "records": d.output.get("records", [])}

    def n_resolve(state: PipelineState) -> PipelineState:
        resolved = []
        for record in state.get("records", []):
            payload = {
                **record,
                # A window has many senders; the party named in the record wins,
                # and the dominant counterparty is the fallback.
                "sender_phone": state["window"].get("counterparty_phone"),
                "sender_name": state["window"].get("counterparty_name"),
            }
            d = rs.execute(payload, trace_id=state["trace_id"])
            resolved.append({**record, "resolution": {**d.output, "confidence": d.confidence}})
        return {**state, "records": resolved}

    def n_triage(state: PipelineState) -> PipelineState:
        triaged = []
        for record in state.get("records", []):
            resolution = record.get("resolution", {})
            payload = {
                "record_type": record.get("record_type"),
                "confidence": min(
                    record.get("confidence", 0), resolution.get("confidence", 1)
                ),
                "party_id": resolution.get("party_id"),
                **(record.get("fields") or {}),
            }
            d = tr.execute(payload, trace_id=state["trace_id"])
            triaged.append({
                **record,
                "action": d.output.get("action", "review"),
                "flags": d.output.get("flags", []),
            })
        return {**state, "records": triaged}

    def n_apply(state: PipelineState) -> PipelineState:
        window = state["window"]
        results = []
        for record in state.get("records", []):
            record_state = {
                "trace_id": state["trace_id"],
                "tenant_id": state["tenant_id"],
                "window_id": window.get("id"),
                "source_message_ids": record.get("source_message_ids", []),
                "interaction": {
                    "id": record.get("anchor_id") or window.get("anchor_id"),
                    "channel": window.get("channel", "whatsapp_export"),
                    "occurred_at": window.get("ended_at"),
                },
                "extraction": {
                    "record_type": record.get("record_type"),
                    "fields": record.get("fields", {}),
                    "confidence": record.get("confidence", 0),
                    "reason": record.get("reason", ""),
                },
                "resolution": record.get("resolution", {}),
                "flags": record.get("flags", []),
            }
            action = record.get("action")
            if action == "commit":
                results.append(commit_record(db, record_state))
            elif action == "review":
                results.append(queue_for_review(db, record_state))
            else:
                results.append({"status": "discarded"})
        return {**state, "results": results}

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
