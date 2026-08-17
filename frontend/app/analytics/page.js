"use client";

import { useCallback, useEffect, useState } from "react";
import TokenGate from "../components/TokenGate";
import Chart from "../components/Chart";
import { api, money, formatNumber } from "../lib/api";

export default function AnalyticsPage() {
  return (
    <TokenGate>
      <Analytics />
    </TokenGate>
  );
}

// Periods an owner actually asks for, not every window a date library can
// express. "Last quarter to date" is a finance word; "this month" is not.
const PERIODS = [
  { key: "mtd", label: "This month" },
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
  { key: "qtd", label: "This quarter" },
  { key: "ytd", label: "This year" },
  { key: "12m", label: "12 months" },
];

const FREQS = [
  { key: "day", label: "Daily" },
  { key: "week", label: "Weekly" },
  { key: "month", label: "Monthly" },
];

function Analytics() {
  const [period, setPeriod] = useState("90d");
  const [kind, setKind] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.analyticsOverview({ period, party_kind: kind || undefined }));
    } catch (err) {
      setError(err.message);
    }
  }, [period, kind]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <ErrorBar message={error} onRetry={load} />;
  if (!data) return <div className="empty">Reading your records…</div>;

  const schema = data.schema;
  const dims = (schema.dimensions || []).filter((d) => d.available);
  const measures = (schema.measures || []).filter((m) => m.available);
  const hasKind = dims.some((d) => d.key === "party_kind");

  return (
    <>
      <header className="bar">
        <h1>Analytics</h1>
        <div className="sub">{describe(schema)}</div>
      </header>

      {data.empty ? (
        <div className="card">
          <p className="muted" style={{ margin: 0 }}>{data.empty}</p>
        </div>
      ) : (
        <>
          <div className="filters">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                className={period === p.key ? "primary" : ""}
                onClick={() => setPeriod(p.key)}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Only offered when parties are actually classified. A filter that
              empties the screen is worse than one that is not there. */}
          {hasKind && (
            <div className="filters">
              {[
                { k: "", l: "Everyone" },
                { k: "customer", l: "Customers" },
                { k: "supplier", l: "Suppliers" },
              ].map((f) => (
                <button
                  key={f.k || "all"}
                  className={kind === f.k ? "primary" : ""}
                  onClick={() => setKind(f.k)}
                >
                  {f.l}
                </button>
              ))}
              {kind && (
                <button className="link-button" onClick={() => setKind("")}>
                  Clear
                </button>
              )}
            </div>
          )}

          <Kpis rows={data.kpis} />
          <Insights period={period} />
          <Trend measures={measures} period={period} kind={kind} />
          <AnalyseBy measures={measures} dims={dims} period={period} kind={kind} />
          <Rankings rankings={data.rankings} />
          <Alerts rows={data.alerts} />
        </>
      )}
    </>
  );
}

function describe(schema) {
  const bits = [];
  if (schema.business_name) bits.push(schema.business_name);
  if (schema.first_record && schema.last_record) {
    const f = (d) =>
      new Date(d).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
    bits.push(`${f(schema.first_record)} – ${f(schema.last_record)}`);
  }
  if (schema.records) bits.push(`${formatNumber(schema.records)} records`);
  return bits.join(" · ");
}

function value(row) {
  if (row.unit === "money") return money(row.value);
  if (row.unit === "quantity") return formatNumber(Math.round(row.value));
  return formatNumber(row.value);
}

// A KPI that cannot be produced still gets a tile, carrying the reason. An
// owner who wants margin should learn that cost is not captured, rather than
// scanning for a number that was silently left out.
function Kpis({ rows }) {
  if (!rows?.length) return null;
  return (
    <div className="kpis">
      {rows.map((r) => (
        <div className={`kpi${r.available ? "" : " unavailable"}`} key={r.key}>
          <div className="kpi-label">{r.label}</div>
          {r.available ? (
            <>
              <div className="kpi-value">{value(r)}</div>
              {r.change_pct != null ? (
                <div className={`kpi-change ${r.change_pct >= 0 ? "up" : "down"}`}>
                  {r.change_pct >= 0 ? "↑" : "↓"} {Math.abs(r.change_pct)}%
                  <span className="muted"> vs previous</span>
                </div>
              ) : (
                <div className="kpi-change muted">{r.no_comparison}</div>
              )}
            </>
          ) : (
            <div className="kpi-why">{r.why_not}</div>
          )}
        </div>
      ))}
    </div>
  );
}

function Insights({ period }) {
  const [rows, setRows] = useState(null);
  const [detail, setDetail] = useState("");

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    api.analyticsInsights(period)
      .then((b) => {
        if (cancelled) return;
        setRows(b.insights || []);
        setDetail(b.detail || "");
      })
      .catch(() => !cancelled && setRows([]));
    return () => {
      cancelled = true;
    };
  }, [period]);

  if (rows === null) return <div className="card"><p className="muted" style={{ margin: 0 }}>Reading what stands out…</p></div>;
  if (!rows.length) return detail ? null : null;

  return (
    <div className="card insights">
      <h3>What stands out</h3>
      <ul>
        {rows.map((r, i) => (
          <li key={i} className={r.kind === "attention" ? "attention" : ""}>
            {r.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Trend({ measures, period, kind }) {
  const [metric, setMetric] = useState("received");
  const [freq, setFreq] = useState("month");
  const [compare, setCompare] = useState(false);
  const [body, setBody] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.analyticsSeries({ metric, freq, period, compare,
                          party_kind: kind || undefined })
      .then((b) => !cancelled && setBody(b))
      .catch(() => !cancelled && setBody(null));
    return () => {
      cancelled = true;
    };
  }, [metric, freq, period, compare, kind]);

  const points = body?.points || [];
  const spec = points.length
    ? `line: ${label(measures, metric)} over time\n` +
      points.map((p) => `${shortDate(p.period, freq)} = ${p.value}`).join("\n")
    : null;

  return (
    <div className="card">
      <h3>Trend</h3>
      <div className="control-row">
        <select value={metric} onChange={(e) => setMetric(e.target.value)}
                aria-label="Measure">
          {measures.map((m) => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
        <select value={freq} onChange={(e) => setFreq(e.target.value)}
                aria-label="Frequency">
          {FREQS.map((f) => (
            <option key={f.key} value={f.key}>{f.label}</option>
          ))}
        </select>
        <label className="check">
          <input type="checkbox" checked={compare}
                 onChange={(e) => setCompare(e.target.checked)} />
          Compare with previous
        </label>
      </div>

      {spec ? <Chart spec={spec} /> : (
        <p className="muted" style={{ marginBottom: 0 }}>
          Nothing recorded for this measure in this period.
        </p>
      )}
      {body?.no_comparison && (
        <p className="muted" style={{ marginBottom: 0 }}>{body.no_comparison}</p>
      )}
      {compare && body?.comparison?.length > 0 && (
        <p className="muted" style={{ marginBottom: 0 }}>
          Previous period totalled{" "}
          {formatNumber(body.comparison.reduce((a, p) => a + p.value, 0))}.
        </p>
      )}
    </div>
  );
}

// The chart type is chosen by the shape of the answer, not by a control: a
// handful of categories is a share, a dozen is a ranking. Asking the owner to
// pick is asking them to do the analyst's job.
function AnalyseBy({ measures, dims, period, kind }) {
  const [metric, setMetric] = useState("received");
  const [dimension, setDimension] = useState("party");
  const [body, setBody] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setError("");
    api.analyticsBreakdown({ metric, dimension, period,
                             party_kind: kind || undefined })
      .then((b) => !cancelled && setBody(b))
      .catch((e) => {
        if (cancelled) return;
        setBody(null);
        setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [metric, dimension, period, kind]);

  const rows = body?.rows || [];
  const spec = rows.length
    ? `${body.chart}: ${label(measures, metric)} by ${dimLabel(dims, dimension)}\n` +
      rows.map((r) => `${r.label} = ${r.value}`).join("\n")
    : null;

  return (
    <div className="card">
      <h3>Analyse by</h3>
      <div className="control-row">
        <select value={metric} onChange={(e) => setMetric(e.target.value)}
                aria-label="Measure">
          {measures.map((m) => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
        <span className="muted">by</span>
        <select value={dimension} onChange={(e) => setDimension(e.target.value)}
                aria-label="Dimension">
          {dims.map((d) => (
            <option key={d.key} value={d.key}>{d.label}</option>
          ))}
        </select>
      </div>

      {error && <p className="muted" style={{ marginBottom: 0 }}>{error}</p>}
      {spec && <Chart spec={spec} />}

      {rows.length > 0 && (
        <div className="breakdown">
          {rows.map((r) => (
            <button className="breakdown-row" key={r.label}
                    onClick={() => setOpen(open === r.label ? null : r.label)}>
              <span className="bd-name">{r.label}</span>
              <span className="bd-value">
                {metric === "received" || metric === "invoiced"
                  ? money(r.value)
                  : formatNumber(r.value)}
              </span>
            </button>
          ))}
        </div>
      )}

      {open && (
        <Drill metric={metric} dimension={dimension} value={open}
               period={period} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

// A chart nobody can open is a chart nobody can check.
function Drill({ metric, dimension, value: v, period, onClose }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    let cancelled = false;
    api.analyticsDrill({ metric, dimension, value: v, period })
      .then((b) => !cancelled && setRows(b.rows || []))
      .catch(() => !cancelled && setRows([]));
    return () => {
      cancelled = true;
    };
  }, [metric, dimension, v, period]);

  return (
    <div className="drill">
      <div className="drill-head">
        <strong>{v}</strong>
        <button className="link-button" onClick={onClose}>Close</button>
      </div>
      {rows === null && <p className="muted">Loading…</p>}
      {rows?.length === 0 && <p className="muted">No records behind this.</p>}
      {rows?.map((r) => (
        <div className="drill-row" key={r.id}>
          <span>{r.party}{r.extra ? ` · ${r.extra}` : ""}</span>
          <span className="muted">
            {r.amount != null ? money(r.amount) : ""} {r.when || ""}
          </span>
        </div>
      ))}
    </div>
  );
}

function Rankings({ rankings }) {
  const blocks = Object.entries(rankings || {}).filter(([, v]) => v?.length);
  if (!blocks.length) return null;
  const titles = {
    parties_by_received: "Paid the most",
    items_by_quantity: "Most ordered",
    cities_by_orders: "Busiest places",
  };
  return (
    <div className="card">
      <h3>Rankings</h3>
      <div className="rank-grid">
        {blocks.map(([key, rows]) => (
          <div key={key}>
            <div className="rank-title">{titles[key] || key}</div>
            {rows.map((r, i) => (
              <div className="rank-row" key={r.label}>
                <span className="rank-n">{i + 1}</span>
                <span className="rank-name">{r.label}</span>
                <span className="rank-v">
                  {key === "parties_by_received" ? money(r.value) : formatNumber(r.value)}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function Alerts({ rows }) {
  if (!rows?.length) return null;
  return (
    <div className="card">
      <h3>Needs attention</h3>
      {rows.map((a, i) => (
        <div className={`alert-row ${a.severity}`} key={i}>
          <div className="alert-head">{a.headline}</div>
          <div className="muted">{a.detail}</div>
        </div>
      ))}
    </div>
  );
}

function ErrorBar({ message, onRetry }) {
  return (
    <>
      <header className="bar"><h1>Analytics</h1></header>
      <div className="banner error">{message}</div>
      <div className="actions"><button onClick={onRetry}>Try again</button></div>
    </>
  );
}

function label(measures, key) {
  return measures.find((m) => m.key === key)?.label || key;
}
function dimLabel(dims, key) {
  return dims.find((d) => d.key === key)?.label || key;
}
function shortDate(iso, freq) {
  const d = new Date(iso);
  if (freq === "day") return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  if (freq === "week") return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}
