"use client";

import { useCallback, useEffect, useState } from "react";
import TokenGate from "../components/TokenGate";
import { api, money, formatNumber } from "../lib/api";

// Fields worth showing as money rather than a bare number.
const MONEY_FIELDS = new Set(["amount", "rate", "balance"]);
const FIELD_LABELS = {
  quality: "Quality",
  quantity: "Quantity",
  unit: "Unit",
  rate: "Rate",
  amount: "Amount",
  mode: "Mode",
  reference: "Reference",
  lr_no: "LR no",
  transporter: "Transporter",
  challan_no: "Challan no",
  order_no: "Order no",
  party: "Party",
};

export default function ReviewPage() {
  return (
    <TokenGate>
      <Review />
    </TokenGate>
  );
}

function Review() {
  const [items, setItems] = useState(null);
  const [index, setIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const [partyName, setPartyName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(0);

  const load = useCallback(async () => {
    try {
      const page = await api.queue();
      setItems(page.items);
      setIndex(0);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const item = items?.[index];

  // Reset the editor whenever the card underneath it changes.
  const currentId = item?.extraction_id;
  useEffect(() => {
    setEditing(false);
    setDraft(item?.fields ? { ...item.fields } : {});
    setPartyName(item?.suggest_create || "");
    // Keyed on the card's identity: re-running on every render would wipe what
    // the owner is halfway through typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setDone((n) => n + 1);
      // Drop the card locally rather than refetching: the owner is holding the
      // phone in a market and the next item should already be there.
      const remaining = items.filter((_, i) => i !== index);
      setItems(remaining);
      setIndex(Math.min(index, Math.max(0, remaining.length - 1)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !items) return <Shell title="Review"><div className="banner error">{error}</div></Shell>;
  if (!items) return <Shell title="Review"><div className="empty">Loading…</div></Shell>;

  if (items.length === 0) {
    return (
      <Shell title="Review" subtitle={done ? `${done} cleared just now` : null}>
        <div className="empty">
          <p style={{ fontSize: 40, margin: 0 }}>✓</p>
          <p>Nothing waiting. Everything the agents were unsure about is handled.</p>
        </div>
        <div className="actions">
          <button onClick={load}>Check again</button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell title="Review" subtitle={`${items.length} waiting${done ? ` · ${done} done` : ""}`}>
      {error && <div className="banner error">{error}</div>}

      <div className="card">
        <div className="chips">
          <span className="chip plain">{item.record_type || "unknown"}</span>
          {item.confidence != null && (
            <span className="chip plain">{Math.round(item.confidence * 100)}% sure</span>
          )}
          {(item.flags || []).map((flag) => (
            <span className="chip" key={flag}>
              {flag}
            </span>
          ))}
        </div>

        {item.message && <div className="msg">{item.message}</div>}
        {item.sender && <p className="muted">from {item.sender}</p>}
        {item.reason && <p className="muted">Agent said: {item.reason}</p>}

        {!editing ? (
          <>
            <dl className="fields">
              {Object.entries(item.fields || {}).map(([key, value]) => (
                <Field key={key} label={FIELD_LABELS[key] || key} name={key} value={value} />
              ))}
              <dt>Party</dt>
              <dd>{item.party_name || item.suggest_create || "not identified"}</dd>
            </dl>

            <div className="actions">
              <button className="primary" disabled={busy} onClick={() => act(() => api.accept(item.extraction_id))}>
                Accept
              </button>
              <button disabled={busy} onClick={() => setEditing(true)}>
                Fix
              </button>
            </div>
            <div className="actions">
              <button className="danger" disabled={busy} onClick={() => act(() => api.reject(item.extraction_id, "Not a record"))}>
                Not a record
              </button>
              {items.length > 1 && (
                <button disabled={busy} onClick={() => setIndex((i) => (i + 1) % items.length)}>
                  Later
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            {Object.keys(draft).length === 0 && <p className="muted">No fields were extracted.</p>}
            {Object.entries(draft).map(([key, value]) => (
              <div key={key}>
                <label htmlFor={`f-${key}`}>{FIELD_LABELS[key] || key}</label>
                <input
                  id={`f-${key}`}
                  value={value === null || value === undefined ? "" : value}
                  inputMode={MONEY_FIELDS.has(key) || key === "quantity" ? "decimal" : "text"}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                />
              </div>
            ))}

            {!item.party_id && (
              <div>
                <label htmlFor="party">Party name</label>
                <input
                  id="party"
                  value={partyName}
                  onChange={(e) => setPartyName(e.target.value)}
                  placeholder="Who is this?"
                />
              </div>
            )}

            <div className="actions">
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  act(() =>
                    api.correct(item.extraction_id, {
                      fields: draft,
                      ...(partyName && !item.party_id ? { party_name: partyName } : {}),
                    })
                  )
                }
              >
                Save
              </button>
              <button disabled={busy} onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}

function Field({ label, name, value }) {
  const shown =
    value === null || value === undefined || value === ""
      ? "—"
      : MONEY_FIELDS.has(name)
        ? money(value)
        : formatNumber(value);
  return (
    <>
      <dt>{label}</dt>
      <dd>{shown}</dd>
    </>
  );
}

function Shell({ title, subtitle, children }) {
  return (
    <>
      <header className="bar">
        <h1>{title}</h1>
        {subtitle && <div className="sub">{subtitle}</div>}
      </header>
      {children}
    </>
  );
}
