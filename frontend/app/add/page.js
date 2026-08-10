"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api, formatNumber } from "../lib/api";
import Empty from "../components/Empty";

export default function AddDataPage() {
  return (
    <TokenGate>
      <AddData />
    </TokenGate>
  );
}

const SOURCES = [
  { key: "upload", label: "From this device" },
  { key: "camera", label: "Take a photo" },
  { key: "accounts", label: "Connected accounts" },
];

function AddData() {
  const [tab, setTab] = useState("upload");
  const [history, setHistory] = useState(null);

  const load = useCallback(async () => {
    setHistory(await api.sources().catch(() => []));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <header className="bar">
        <h1>Add data</h1>
        <div className="sub">Chats, bills, spreadsheets — any time, not just at setup</div>
      </header>

      <div className="filters">
        {SOURCES.map((s) => (
          <button
            key={s.key}
            className={tab === s.key ? "primary" : ""}
            onClick={() => setTab(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {tab === "upload" && <Picker onDone={load} />}
      {tab === "camera" && <Picker camera onDone={load} />}
      {tab === "accounts" && <Accounts />}

      <History rows={history} />
    </>
  );
}

// One component for both device files and camera capture. The only difference
// is the input's accept/capture attributes — the parse, estimate and dedup
// path behind it is identical to onboarding, deliberately: two ingestion
// routes would drift apart and one of them would quietly stop deduping.
function Picker({ camera = false, onDone }) {
  const [files, setFiles] = useState([]);
  const [estimate, setEstimate] = useState(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  async function pick(picked) {
    setFiles(picked);
    setEstimate(null);
    setResult(null);
    setError(null);
    if (!picked.length) return;
    setChecking(true);
    try {
      setEstimate(await api.estimateUpload(picked));
    } catch {
      // The estimate is a courtesy; never block the upload on it.
      setEstimate(null);
    } finally {
      setChecking(false);
    }
  }

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const body = await api.ingestBatch(files);
      setResult(body);
      setFiles([]);
      setEstimate(null);
      if (inputRef.current) inputRef.current.value = "";
      onDone?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error && <div className="banner error">{error}</div>}

      {result && (
        <div className="banner">
          {result.new_messages > 0
            ? `${formatNumber(result.new_messages)} new records are being read now.`
            : "Nothing new — everything in that was already read."}
          {result.duplicates > 0 &&
            ` ${formatNumber(result.duplicates)} were already here and were skipped.`}{" "}
          <Link href="/today">See progress</Link>
        </div>
      )}

      <div className="card">
        {camera ? (
          <>
            <label htmlFor="shot" style={{ fontWeight: 600 }}>
              Photograph a bill, challan or ledger page
            </label>
            <input
              ref={inputRef}
              id="shot"
              type="file"
              accept="image/*"
              // Opens the camera directly rather than the gallery, which is
              // the whole point when someone is standing at the counter with
              // a challan in their hand.
              capture="environment"
              multiple
              onChange={(e) => pick([...(e.target.files || [])])}
            />
            <p className="muted">
              Take as many as you like. Photograph the whole page, straight on,
              in good light — the text is read from the picture.
            </p>
          </>
        ) : (
          <>
            <label htmlFor="files" style={{ fontWeight: 600 }}>
              Choose files
            </label>
            <input
              ref={inputRef}
              id="files"
              type="file"
              accept=".txt,.zip,.xlsx,.xlsm,.jpg,.jpeg,.png,.webp"
              multiple
              onChange={(e) => pick([...(e.target.files || [])])}
            />
            <p className="muted">
              WhatsApp chat exports (.txt or .zip), Tally and Excel sheets, or
              photos of bills. Pick as many as you like.
            </p>
          </>
        )}

        {checking && <p className="muted">Reading the files…</p>}

        {estimate && (
          <div className="banner" style={{ marginTop: 4 }}>
            <strong>{formatNumber(estimate.new_messages)} new</strong>
            {estimate.media > 0 && ` · ${formatNumber(estimate.media)} photos`}
            {estimate.new_messages > 0 && (
              <>
                {" "}· about {estimate.estimated_minutes} minute
                {estimate.estimated_minutes === 1 ? "" : "s"} to read
              </>
            )}
            {estimate.duplicates > 0 && (
              <> · {formatNumber(estimate.duplicates)} already read, will be skipped</>
            )}
          </div>
        )}

        {estimate?.files?.some((f) => f.error) && (
          <div className="banner error" style={{ marginTop: 8 }}>
            {estimate.files
              .filter((f) => f.error)
              .map((f) => (
                <div key={f.filename}>
                  {f.filename}: {f.error}
                </div>
              ))}
            The rest will still be read.
          </div>
        )}

        <div className="actions">
          <button
            className="primary"
            style={{ width: "100%" }}
            disabled={busy || !files.length || estimate?.new_messages === 0}
            onClick={send}
          >
            {busy
              ? "Sending…"
              : files.length
                ? `Read ${files.length} ${files.length === 1 ? "file" : "files"}`
                : "Choose files first"}
          </button>
        </div>
      </div>
    </>
  );
}

function Accounts() {
  const [inbound, setInbound] = useState(null);
  const [gmail, setGmail] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.inbound().then(setInbound).catch(() => setInbound({ configured: false }));
    api.gmailStatus().then(setGmail).catch(() => setGmail(null));
  }, []);

  return (
    <>
      {/* Forwarding leads. It is the one that keeps working. */}
      <div className="card">
        <h3>Forward your invoices here</h3>
        {inbound?.configured ? (
          <>
            <p
              style={{
                fontFamily: "ui-monospace, monospace",
                fontSize: 15,
                wordBreak: "break-all",
                background: "var(--card-2)",
                padding: "12px 14px",
                borderRadius: 10,
                margin: "4px 0 12px",
              }}
            >
              {inbound.address}
            </p>
            <div className="actions">
              <button
                className="primary"
                style={{ width: "100%" }}
                onClick={() => {
                  navigator.clipboard?.writeText(inbound.address);
                  setCopied(true);
                }}
              >
                {copied ? "Copied" : "Copy address"}
              </button>
            </div>
            <ul style={{ paddingLeft: 18, lineHeight: 1.7, margin: "12px 0 0" }}>
              {inbound.how.map((line) => (
                <li key={line} style={{ marginBottom: 6 }}>
                  {line}
                </li>
              ))}
            </ul>
            {inbound.limits?.length > 0 && (
              <p className="muted" style={{ marginBottom: 0 }}>
                {inbound.limits.join(" ")}
              </p>
            )}
          </>
        ) : (
          <p className="muted" style={{ marginBottom: 0 }}>
            {inbound
              ? "Email forwarding is not switched on yet."
              : "Loading…"}
          </p>
        )}
      </div>

      <div className="card">
        <div className="row">
          <div>
            <div style={{ fontWeight: 600 }}>Connect Gmail directly</div>
            <div className="muted">
              {gmail?.detail ||
                "Reads new invoices and purchase orders without forwarding."}
            </div>
          </div>
          <span className="chip plain">
            {gmail?.available ? "Available" : "Not yet"}
          </span>
        </div>
        <div className="row">
          <div>
            <div style={{ fontWeight: 600 }}>WhatsApp Business</div>
            <div className="muted">
              Continuous sync, so you stop exporting chats by hand.
            </div>
          </div>
          <span className="chip plain">Coming soon</span>
        </div>
      </div>
    </>
  );
}

function History({ rows }) {
  if (!rows) return <div className="empty">Loading…</div>;

  if (!rows.length) {
    return (
      <section className="feed">
        <h2>Imported so far</h2>
        <Empty title="Nothing imported yet">
          Whatever you add above appears here, so you can see what has been
          read rather than trying to remember.
        </Empty>
      </section>
    );
  }

  return (
    <section className="feed">
      <h2>
        Imported so far
        <span className="count">{rows.length}</span>
      </h2>
      {rows.map((r) => (
        <div className="list-row" key={r.id}>
          <div className="top">
            <span className="name">{r.label || r.kind}</span>
            <span className="muted" style={{ fontSize: 14 }}>
              {new Date(r.created_at).toLocaleDateString("en-IN", {
                day: "numeric",
                month: "short",
              })}
            </span>
          </div>
          <div className="sub">
            {r.status === "failed" ? (
              <span className="warn">{r.detail || "Could not be read"}</span>
            ) : (
              <>
                {formatNumber(r.messages)} record{r.messages === 1 ? "" : "s"}
                {r.media > 0 && ` · ${formatNumber(r.media)} photos`}
                {r.duplicates > 0 && ` · ${formatNumber(r.duplicates)} already had`}
                {` · from ${r.kind === "upload" ? "a file" : r.kind}`}
              </>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
