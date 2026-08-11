"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api, formatNumber } from "../lib/api";
import Empty from "../components/Empty";
import FilePicker from "../components/FilePicker";
import VoiceNote from "../components/VoiceNote";

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
  { key: "voice", label: "Speak" },
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
      {tab === "voice" && <Voice onDone={load} />}
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
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [nonce, setNonce] = useState(0);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const body = await api.ingestBatch(files);
      setResult(body);
      setFiles([]);
      setEstimate(null);
      // Remounting the picker is the simplest way to clear both its internal
      // list and the native input, which does not reset itself.
      setNonce((n) => n + 1);
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

      <FilePicker
        key={`${camera ? "cam" : "files"}-${nonce}`}
        id={camera ? "shot" : "files"}
        label={camera ? "Photograph a bill, challan or ledger page" : "Choose files"}
        accept={camera ? "image/*" : ".txt,.zip,.xlsx,.xlsm,.jpg,.jpeg,.png,.webp"}
        capture={camera ? "environment" : undefined}
        hint={
          camera
            ? "Take as many as you like. Photograph the whole page, straight on, in good light — the text is read from the picture."
            : "WhatsApp chat exports (.txt or .zip), Tally and Excel sheets, or photos of bills. Pick as many as you like."
        }
        onEstimate={(picked, body) => {
          setFiles(picked);
          setEstimate(body);
        }}
      >
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
      </FilePicker>
    </>
  );
}

// A voice note is just another upload once it exists — same batch endpoint,
// same dedup, same backfill. Gemini reads the audio itself.
function Voice({ onDone }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function send(file) {
    setBusy(true);
    setError(null);
    try {
      const body = await api.ingestBatch([file]);
      setResult(body);
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
          Saved. It is being read now. <Link href="/today">See progress</Link>
        </div>
      )}
      {busy && <div className="banner">Sending…</div>}
      <VoiceNote
        label="Say what happened"
        hint="An order, a payment, a rate you agreed — say it the way you would tell someone in the shop."
        onRecorded={send}
      />
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
                {formatNumber(r.messages)} message{r.messages === 1 ? "" : "s"}
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
