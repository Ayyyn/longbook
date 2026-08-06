"use client";

import { useCallback, useEffect, useState } from "react";
import TokenGate from "../components/TokenGate";
import { api, formatNumber } from "../lib/api";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "overrides", label: "You corrected" },
  { key: "error", label: "Failed" },
];

export default function ActivityPage() {
  return (
    <TokenGate>
      <Activity />
    </TokenGate>
  );
}

function Activity() {
  const [summary, setSummary] = useState(null);
  const [runs, setRuns] = useState(null);
  const [filter, setFilter] = useState("all");
  const [openTrace, setOpenTrace] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async (which) => {
    try {
      const options =
        which === "overrides"
          ? { overrides_only: true }
          : which === "error"
            ? { outcome: "error" }
            : {};
      const [stats, feed] = await Promise.all([api.agentSummary(), api.agentRuns(options)]);
      setSummary(stats);
      setRuns(feed.items);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load(filter);
  }, [load, filter]);

  if (error) {
    return (
      <>
        <Header />
        <div className="banner error">{error}</div>
      </>
    );
  }
  if (!summary || !runs) return <div className="empty">Loading…</div>;

  return (
    <>
      <Header />

      <div className="stat-grid">
        <div className="stat">
          <div className="label">Decisions</div>
          <div className="value">{formatNumber(summary.runs)}</div>
          <div className="note">{summary.runs_today} today</div>
        </div>
        <div className="stat">
          <div className="label">You corrected</div>
          <div className="value">{Math.round(summary.override_rate * 100)}%</div>
          <div className="note">{summary.overrides} of {summary.runs}</div>
        </div>
        <div className="stat">
          <div className="label">Speed</div>
          <div className="value">
            {summary.avg_latency_ms ? `${(summary.avg_latency_ms / 1000).toFixed(1)}s` : "—"}
          </div>
          <div className="note">average</div>
        </div>
        <div className="stat">
          <div className="label">Cost</div>
          <div className="value">${summary.cost_usd.toFixed(2)}</div>
          <div className="note">{formatNumber(summary.input_tokens + summary.output_tokens)} tokens</div>
        </div>
      </div>

      {summary.by_agent.length > 0 && (
        <div className="card">
          <strong>By agent</strong>
          {summary.by_agent.map((row) => (
            <div className="row" key={row.agent}>
              <div>
                <div>{row.agent}</div>
                <div className="muted">
                  {row.runs} runs · {Math.round(row.override_rate * 100)}% corrected
                  {row.errors > 0 ? ` · ${row.errors} failed` : ""}
                </div>
              </div>
              <div className="muted">
                {row.avg_confidence != null ? `${Math.round(row.avg_confidence * 100)}%` : "—"}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="chips" style={{ marginTop: 14 }}>
        {FILTERS.map((option) => (
          <button
            key={option.key}
            onClick={() => setFilter(option.key)}
            style={{ flex: "0 0 auto", minHeight: 40, padding: "0 14px" }}
            className={filter === option.key ? "primary" : ""}
          >
            {option.label}
          </button>
        ))}
      </div>

      {runs.length === 0 ? (
        <div className="empty">Nothing here yet.</div>
      ) : (
        runs.map((run) => (
          <RunCard
            key={run.id}
            run={run}
            open={openTrace === run.trace_id}
            onToggle={() => setOpenTrace(openTrace === run.trace_id ? null : run.trace_id)}
          />
        ))
      )}
    </>
  );
}

function RunCard({ run, open, onToggle }) {
  const [trace, setTrace] = useState(null);

  useEffect(() => {
    if (!open || !run.trace_id || trace) return;
    api.agentTrace(run.trace_id).then(setTrace).catch(() => setTrace(null));
  }, [open, run.trace_id, trace]);

  return (
    <div className="card">
      <div className="chips">
        <span className="chip plain">{run.agent}</span>
        {run.confidence != null && (
          <span className="chip plain">{Math.round(run.confidence * 100)}% sure</span>
        )}
        {run.outcome === "error" && <span className="chip">failed</span>}
        {run.outcome === "escalated" && <span className="chip">escalated</span>}
        {run.human_override && <span className="chip">you corrected this</span>}
      </div>

      {run.subject && <div className="msg">{run.subject}</div>}
      {run.rationale && <p className="muted">{run.rationale}</p>}
      {run.error && <p className="muted">{run.error}</p>}

      <div className="muted">
        {run.model} · {run.prompt_version} · {run.latency_ms ?? "—"}ms
        {run.cost_usd ? ` · $${run.cost_usd.toFixed(4)}` : ""}
        {run.created_at ? ` · ${new Date(run.created_at).toLocaleString("en-IN")}` : ""}
      </div>

      {run.trace_id && (
        <div className="actions">
          <button onClick={onToggle}>{open ? "Hide steps" : "Show what happened"}</button>
        </div>
      )}

      {open && trace && (
        <div style={{ marginTop: 10 }}>
          {trace.steps.map((step, index) => (
            <div className="row" key={`${step.agent}-${index}`}>
              <div>
                <div>
                  {index + 1}. {step.agent}
                </div>
                <div className="muted">{step.rationale || step.outcome}</div>
              </div>
              <div className="muted">
                {step.confidence != null ? `${Math.round(step.confidence * 100)}%` : "—"}
              </div>
            </div>
          ))}
          <p className="muted">
            Result: {trace.record_type || "—"} · {trace.outcome || "—"}
          </p>
        </div>
      )}
    </div>
  );
}

function Header() {
  return (
    <header className="bar">
      <h1>Agent activity</h1>
      <div className="sub">Every decision, and how often you disagreed</div>
    </header>
  );
}
