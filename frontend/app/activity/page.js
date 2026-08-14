"use client";

import { useCallback, useEffect, useState } from "react";
import TokenGate from "../components/TokenGate";
import { api, formatNumber } from "../lib/api";
import Empty, { BackfillProgress } from "../components/Empty";

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
  const [job, setJob] = useState(null);

  const load = useCallback(async (which) => {
    try {
      const options =
        which === "overrides"
          ? { overrides_only: true }
          : which === "error"
            ? { outcome: "error" }
            : {};
      const running = await api.latestJob().catch(() => null);
      setJob(running);
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

  // setup_required means the messages are held but nothing can read them
  // until the interview is answered — the opposite of "in progress".
  const blocked = job?.state === "setup_required";
  const working =
    job && !blocked && job.state !== "done" && job.state !== "failed";

  if (summary.runs === 0) {
    return (
      <>
        <Header />
        {blocked ? (
          <SetupIncomplete held={job.total} />
        ) : working ? (
          <BackfillProgress job={job} />
        ) : (
          <Empty title="No decisions yet">
            Every time an agent reads a message and decides something, it is
            logged here — what it chose, how sure it was, how long it took and
            what it cost. Nothing has run yet, so there is nothing to show.
          </Empty>
        )}
      </>
    );
  }

  return (
    <>
      <Header />
      {blocked && <SetupIncomplete held={job.total} />}
      {working && <BackfillProgress job={job} />}

      {/* The four numbers that say whether this is working. Auto-commit
          alone understates it: a record written with one blank to confirm is
          nearly done, so "written" sits beside it. */}
      <div className="stat-grid">
        <div className="stat">
          <div className="value">
            {Math.round((summary.throughput?.written_rate ?? 0) * 100)}%
          </div>
          <div className="note">Records written</div>
        </div>
        <div className="stat">
          <div className="value">
            {Math.round((summary.throughput?.auto_commit_rate ?? 0) * 100)}%
          </div>
          <div className="note">Handled without asking</div>
        </div>
        <div className="stat">
          <div className="value">
            {summary.throughput?.fields_per_review_item ?? "—"}
          </div>
          <div className="note">Questions per item</div>
        </div>
        <div className="stat">
          <div className="value">{Math.round(summary.override_rate * 100)}%</div>
          <div className="note">Corrections by you</div>
        </div>
      </div>

      <div className="card">
        <h3>Cost and speed</h3>
        <div className="row">
          <div className="muted">Decisions</div>
          <div style={{ fontWeight: 650 }}>
            {formatNumber(summary.runs)}{" "}
            <span className="muted">({summary.runs_today} today)</span>
          </div>
        </div>
        <div className="row">
          <div className="muted">Average time</div>
          <div style={{ fontWeight: 650 }}>
            {summary.avg_latency_ms ? `${(summary.avg_latency_ms / 1000).toFixed(1)}s` : "—"}
          </div>
        </div>
        <div className="row">
          <div className="muted">Spend</div>
          <div style={{ fontWeight: 650 }}>
            ${summary.cost_usd.toFixed(2)}{" "}
            <span className="muted">
              ({formatNumber(summary.input_tokens + summary.output_tokens)} tokens)
            </span>
          </div>
        </div>
        {summary.errors > 0 && (
          <div className="row">
            <div className="muted">Failed</div>
            <div style={{ fontWeight: 650 }}>{summary.errors}</div>
          </div>
        )}
      </div>

      {summary.by_agent.length > 0 && (
        <div className="card">
          <h3>By agent</h3>
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

      <section className="feed">
        <h2>Recent decisions</h2>
        <div className="filters">
          {FILTERS.map((option) => (
            <button
              key={option.key}
              onClick={() => setFilter(option.key)}
              className={filter === option.key ? "primary" : ""}
            >
              {option.label}
            </button>
          ))}
        </div>
      </section>

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

      {runs.length > 0 && (
        <div className="actions">
          <button style={{ width: "100%" }} onClick={() => exportCsv(runs)}>
            Export activity log
          </button>
        </div>
      )}
    </>
  );
}

// The runs already on screen, as a CSV the owner can open in Excel or hand to
// an auditor. Only what is loaded — the filter above decides what goes in.
function exportCsv(runs) {
  const columns = [
    "created_at",
    "agent",
    "subject",
    "outcome",
    "confidence",
    "human_override",
    "model",
    "prompt_version",
    "latency_ms",
    "cost_usd",
    "trace_id",
  ];
  const cell = (value) =>
    value == null ? "" : `"${String(value).replace(/"/g, '""')}"`;
  const csv = [
    columns.join(","),
    ...runs.map((run) => columns.map((c) => cell(run[c])).join(",")),
  ].join("\n");

  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "activity-log.csv";
  link.click();
  URL.revokeObjectURL(url);
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
