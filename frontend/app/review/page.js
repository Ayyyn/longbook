"use client";

import { useCallback, useEffect, useState } from "react";
import TokenGate from "../components/TokenGate";
import { api, money, formatNumber } from "../lib/api";
import Empty, { SetupIncomplete, BackfillProgress } from "../components/Empty";

// Fields worth showing as money rather than a bare number.
const MONEY_FIELDS = new Set(["amount", "rate", "balance"]);
const NUMERIC_FIELDS = new Set(["amount", "rate", "balance", "quantity"]);

const FIELD_LABELS = {
  party: "Party",
  quality: "Quality",
  quantity: "Quantity",
  unit: "Unit",
  rate: "Rate",
  amount: "Amount",
  mode: "Mode",
  reference: "Reference",
  received_on: "Received on",
  lr_no: "LR no",
  transporter: "Transporter",
  challan_no: "Challan no",
  order_no: "Order no",
  delivery_date: "Delivery by",
  status: "Status",
  notes: "Notes",
};

const TYPE_LABELS = {
  order: "Order",
  payment: "Payment",
  dispatch: "Dispatch",
  complaint: "Complaint",
  quote: "Quote",
  enquiry: "Enquiry",
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
  const [answers, setAnswers] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [job, setJob] = useState(null);
  const [setup, setSetup] = useState(false);
  const [done, setDone] = useState(0);

  const load = useCallback(async () => {
    const running = await api.latestJob().catch(() => null);
    setJob(running);
    try {
      const page = await api.queue();
      setItems(page.items);
      setIndex(0);
      setSetup(false);
      setError(null);
    } catch (err) {
      if (err.status === 409) setSetup(true);
      else setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const item = items?.[index];
  const currentId = item?.extraction_id;

  useEffect(() => {
    // Pre-fill with what the agent already has, so "Fix" is editing rather
    // than re-entering. Keyed on the card's identity — re-running on every
    // render would wipe what the owner is halfway through typing.
    setAnswers({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setDone((n) => n + 1);
      const remaining = items.filter((_, i) => i !== index);
      setItems(remaining);
      setIndex(Math.min(index, Math.max(0, remaining.length - 1)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const working = job && job.state !== "done" && job.state !== "failed";

  if (setup) {
    return (
      <Shell title="Review">
        {working ? <BackfillProgress job={job} /> : <SetupIncomplete />}
      </Shell>
    );
  }

  if (error && !items) {
    return (
      <Shell title="Review">
        <div className="banner error">{error}</div>
      </Shell>
    );
  }
  if (!items) return <Shell title="Review"><div className="empty">Loading…</div></Shell>;

  if (items.length === 0) {
    return (
      <Shell title="Review" subtitle={done ? `${done} cleared just now` : null}>
        {working ? (
          <BackfillProgress job={job} />
        ) : done > 0 ? (
          <div className="empty">
            <p style={{ fontSize: 40, margin: 0 }}>✓</p>
            <p>Nothing waiting. Everything the agents were unsure about is handled.</p>
          </div>
        ) : (
          // A tick and "everything is handled" would be a lie on a tenant that
          // has never had a message read.
          <Empty title="Nothing to confirm" action="Check again" onAction={load}>
            When an agent reads a message and is not sure about it — a missing
            rate, a party it cannot place — the record waits here for you to
            confirm. Nothing is waiting right now.
          </Empty>
        )}
      </Shell>
    );
  }

  const pending = item.pending_fields || [];
  const confirmed = Object.entries(item.fields || {}).filter(
    ([key, value]) => !pending.includes(key) && value !== null && value !== ""
  );
  const failedRule = (item.validations || []).find((v) => v.status === "fail");

  function submit() {
    // Send what the agent had plus what the owner just filled in. Untouched
    // fields keep their committed values rather than being re-sent as blanks.
    const merged = { ...(item.fields || {}), ...answers };
    return act(() =>
      api.correct(item.extraction_id, {
        fields: merged,
        ...(answers.__party && !item.party_id ? { party_name: answers.__party } : {}),
      })
    );
  }

  return (
    <Shell
      title="Review"
      subtitle={`${items.length} waiting${done ? ` · ${done} done` : ""}`}
    >
      {error && <div className="banner error">{error}</div>}

      <div className="card">
        <div className="chips">
          <span className="chip plain">{TYPE_LABELS[item.record_type] || item.record_type}</span>
          {item.party_name && <span className="chip plain">{item.party_name}</span>}
          {item.confidence != null && (
            <span className="chip plain">{Math.round(item.confidence * 100)}% sure</span>
          )}
          {item.committed_type && <span className="chip plain">saved, needs one detail</span>}
        </div>

        {/* What is already known and committed, as a plain table. */}
        {confirmed.length > 0 ? (
          <div className="record-table">
            {confirmed.map(([key, value]) => (
              <Field key={key} name={key} value={value} />
            ))}
          </div>
        ) : (
          <p className="muted">
            Nothing else was captured — read the conversation below before
            deciding.
          </p>
        )}

        {/* The one thing being asked. */}
        {pending.length === 0 ? (
          <p className="muted" style={{ marginTop: 12 }}>
            {item.reason || "Confirm this record."}
          </p>
        ) : (
          pending.map((name) => (
            <div className="field-ask" key={name}>
              <label htmlFor={`ask-${name}`}>{FIELD_LABELS[name] || name}</label>
              <p className="why">
                {item.pending_reasons?.[name] || "Needs confirming."}
              </p>
              {name === "party" && !item.party_id ? (
                <input
                  id="ask-party"
                  value={answers.__party ?? (item.suggest_create || "")}
                  onChange={(e) => setAnswers({ ...answers, __party: e.target.value })}
                  placeholder="Who is this?"
                  autoComplete="off"
                />
              ) : (
                <input
                  id={`ask-${name}`}
                  value={answers[name] ?? ""}
                  inputMode={NUMERIC_FIELDS.has(name) ? "decimal" : "text"}
                  onChange={(e) => setAnswers({ ...answers, [name]: e.target.value })}
                  placeholder={FIELD_LABELS[name] || name}
                  autoComplete="off"
                />
              )}
            </div>
          ))
        )}

        {failedRule && (
          <p className="muted">
            Check that disagreed: <strong>{failedRule.rule}</strong>
            {failedRule.detail ? ` — ${failedRule.detail}` : ""}
          </p>
        )}

        <div className="actions">
          <button
            disabled={busy}
            onClick={() =>
              items.length > 1
                ? setIndex((i) => (i + 1) % items.length)
                : act(() => api.accept(item.extraction_id))
            }
          >
            Skip
          </button>
          <button className="primary" disabled={busy} onClick={submit}>
            Confirm
          </button>
        </div>
        <button
          className="link-button"
          disabled={busy}
          onClick={() => act(() => api.reject(item.extraction_id, "Not a record"))}
        >
          Not {"aeiou".includes((item.record_type || "")[0]) ? "an" : "a"}{" "}
          {TYPE_LABELS[item.record_type]?.toLowerCase() || "record"}
        </button>

        {/* Where this came from — collapsed, because the owner only opens it
            when the extracted fields look wrong. */}
        {(item.conversation?.length > 0 || item.message) && (
          <details className="source">
            <summary>Where this came from</summary>
            {item.conversation?.length > 0 ? (
              item.conversation.map((m) => (
                <div className={`msg-line${m.cited ? " cited" : ""}`} key={m.id}>
                  <span className="who">
                    {m.sender}
                    {m.occurred_at
                      ? ` · ${new Date(m.occurred_at).toLocaleDateString("en-IN")}`
                      : ""}
                  </span>
                  {m.body}
                </div>
              ))
            ) : (
              <div className="msg-line">{item.message}</div>
            )}
          </details>
        )}
      </div>
    </Shell>
  );
}

function Field({ name, value }) {
  let shown;
  if (Array.isArray(value)) {
    shown = value
      .map((line) =>
        typeof line === "object" && line
          ? [line.quality, line.quantity && `${formatNumber(line.quantity)}${line.unit || ""}`,
             line.rate && `@${line.rate}`].filter(Boolean).join(" ")
          : String(line)
      )
      .join("; ");
  } else if (value === null || value === undefined || value === "") {
    shown = "—";
  } else if (MONEY_FIELDS.has(name)) {
    shown = money(value);
  } else if (typeof value === "number") {
    shown = formatNumber(value);
  } else {
    shown = String(value);
  }
  return (
    <div className="line">
      <span className="k">{FIELD_LABELS[name] || name}</span>
      <span className="v">{shown}</span>
    </div>
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
