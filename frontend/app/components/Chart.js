"use client";

import { formatNumber } from "../lib/api";

// Charts, drawn as plain SVG.
//
// No charting library on purpose: the whole need is "show me these eight
// numbers next to each other", and a bar or line chart in SVG is a hundred
// lines against a hundred kilobytes of dependency that this audience would
// download over mobile data.
//
// The bars carry their own labels and values because the reader is on a phone
// in daylight and will not hover over anything. Anything the chart cannot
// draw falls back to a table, which is still an answer.

const PALETTE = ["#0d5c34", "#2f7d52", "#4f9d71", "#74bd92", "#9bdcb4"];

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / magnitude) * magnitude;
}

export default function Chart({ spec }) {
  const rows = (spec?.data || []).filter(
    (d) => d && d.label != null && Number.isFinite(Number(d.value)),
  );
  if (!rows.length) return null;

  const type = (spec.type || "bar").toLowerCase();
  const title = spec.title || null;
  const unit = spec.unit || "";
  const values = rows.map((r) => Number(r.value));
  const max = niceMax(Math.max(...values));

  if (type === "line") return <LineChart rows={rows} max={max} title={title} unit={unit} />;
  if (type === "pie" || type === "share") {
    return <ShareChart rows={rows} title={title} unit={unit} />;
  }
  return <BarChart rows={rows} max={max} title={title} unit={unit} />;
}

function Caption({ title }) {
  if (!title) return null;
  return <div className="chart-title">{title}</div>;
}

function BarChart({ rows, max, title, unit }) {
  return (
    <div className="chart">
      <Caption title={title} />
      {rows.map((row, i) => {
        const value = Number(row.value);
        const pct = Math.max(1, Math.round((value / max) * 100));
        return (
          <div className="chart-row" key={i}>
            <div className="chart-label">{row.label}</div>
            <div className="chart-track">
              <div
                className="chart-bar"
                style={{ width: `${pct}%`, background: PALETTE[i % PALETTE.length] }}
              />
            </div>
            <div className="chart-value">
              {unit === "%" ? `${formatNumber(value)}%` : formatNumber(value)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Percentages of a whole, as one stacked strip plus a key. Easier to read on a
// narrow screen than a pie, and it does not need any trigonometry to be right.
function ShareChart({ rows, title, unit }) {
  const total = rows.reduce((sum, r) => sum + Number(r.value), 0) || 1;
  return (
    <div className="chart">
      <Caption title={title} />
      <div className="chart-stack">
        {rows.map((row, i) => (
          <div
            key={i}
            className="chart-slice"
            style={{
              width: `${(Number(row.value) / total) * 100}%`,
              background: PALETTE[i % PALETTE.length],
            }}
            title={`${row.label}: ${row.value}`}
          />
        ))}
      </div>
      <div className="chart-key">
        {rows.map((row, i) => (
          <div className="chart-key-item" key={i}>
            <span className="chart-dot" style={{ background: PALETTE[i % PALETTE.length] }} />
            {row.label}
            <strong>
              {Math.round((Number(row.value) / total) * 100)}
              {unit === "%" ? "%" : "%"}
            </strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function LineChart({ rows, max, title, unit }) {
  const width = 320;
  const height = 120;
  const step = rows.length > 1 ? width / (rows.length - 1) : width;
  const points = rows
    .map((row, i) => {
      const x = i * step;
      const y = height - (Number(row.value) / max) * (height - 10) - 5;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <div className="chart">
      <Caption title={title} />
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart-svg"
        preserveAspectRatio="none"
        role="img"
        aria-label={title || "chart"}
      >
        <polyline points={points} fill="none" stroke={PALETTE[0]} strokeWidth="2.5" />
        {rows.map((row, i) => {
          const x = i * step;
          const y = height - (Number(row.value) / max) * (height - 10) - 5;
          return <circle key={i} cx={x} cy={y} r="3.5" fill={PALETTE[0]} />;
        })}
      </svg>
      <div className="chart-key">
        {rows.map((row, i) => (
          <div className="chart-key-item" key={i}>
            {row.label}
            <strong>
              {unit === "%" ? `${formatNumber(row.value)}%` : formatNumber(row.value)}
            </strong>
          </div>
        ))}
      </div>
    </div>
  );
}
