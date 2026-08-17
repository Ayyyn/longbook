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

// What "From this device" will offer. Both MIME types and extensions are
// listed on purpose: Android's picker filters on MIME and shows nothing for a
// bare ".xlsx", while desktop browsers match extensions more reliably. Give it
// only extensions — as this did — and Android quietly falls back to showing
// images alone, which is why this screen looked like a photo picker.
//
// Keep in step with SUPPORTED in app/services/intake.py. Anything offered here
// and not handled there is a file the owner picks and then gets a 415 for.
const DEVICE_ACCEPT = [
  ".txt,text/plain",
  ".zip,application/zip,application/x-zip-compressed",
  ".pdf,application/pdf",
  ".csv,text/csv",
  ".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".jpg,.jpeg,.png,.webp,.heic,.heif,image/*",
  ".ogg,.oga,.opus,.m4a,.mp3,.wav,.aac,.webm,audio/*",
].join(",");

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
        accept={camera ? "image/*" : DEVICE_ACCEPT}
        capture={camera ? "environment" : undefined}
        hint={
          camera
            ? "Take as many as you like. Photograph the whole page, straight on, in good light — the text is read from the picture."
            : "Chat exports, PDFs, bills, sheets, photos or voice notes. Pick as many as you like."
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
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.inbound().then(setInbound).catch(() => setInbound({ configured: false }));
  }, []);

  return (
    <>
      <Mailbox />

      {/* Forwarding stays. It is the one that works without a grant, and the
          fallback for anyone who does not want to connect a mailbox. */}
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

// The connected mailbox.
//
// Leads the screen because it is the version that keeps working after the
// owner stops thinking about it — forwarding only ever carries the mail
// somebody remembered to forward.
//
// The one thing this has to be unambiguous about is what we do with the
// access: read, never send. An owner handing over their mailbox is entitled
// to know that in the same breath as the button.
function Mailbox() {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setState(await api.mailbox().catch(() => ({ available: false, accounts: [] })));
  }, []);

  // The first pull of a mailbox with years in it does not fit in one request,
  // so the server hands back `more` and we come back for the rest. Looping
  // here rather than leaving it to the ten-minute sweep is the difference
  // between the history being there when the owner looks and being there an
  // hour later.
  //
  // Capped so a mailbox that keeps saying "more" cannot spin forever; the
  // sweep picks up anything past the cap.
  const pull = useCallback(async () => {
    setBusy("sync");
    let total = 0;
    try {
      for (let round = 0; round < 20; round += 1) {
        const out = await api.mailboxSync();
        total += out.records || 0;
        setNote(
          out.more
            ? `Reading your mail — ${formatNumber(total)} so far…`
            : total
              ? `Read ${formatNumber(total)} message${total === 1 ? "" : "s"}.`
              : "Nothing new since the last check.",
        );
        await load();
        if (!out.more) break;
      }
    } catch {
      setNote(
        total
          ? `Read ${formatNumber(total)} message${total === 1 ? "" : "s"}, then stopped. The rest follows automatically.`
          : "Could not check just now.",
      );
    }
    setBusy("");
  }, [load]);

  useEffect(() => {
    load();
    // The callback sends the owner back here with the outcome in the URL.
    // Read once, then strip it, so a refresh does not re-announce it.
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("mail");
    if (outcome) {
      setNote(
        {
          connected: "Mailbox connected. Reading your mail now.",
          failed: "That did not go through. Try connecting again.",
          expired: "That link had expired. Try connecting again.",
        }[outcome] || "",
      );
      window.history.replaceState({}, "", window.location.pathname);
      // Connecting is the moment the owner wants to see something happen, so
      // pull straight away rather than waiting for the sweep.
      if (outcome === "connected") pull();
    }
  }, [load, pull]);

  const connect = async () => {
    setBusy("connect");
    try {
      const { url } = await api.mailboxConnect();
      window.location.href = url;
    } catch {
      setNote("Could not start. Try again.");
      setBusy("");
    }
  };


  const disconnect = async (id) => {
    setBusy(id);
    await api.mailboxDisconnect(id).catch(() => {});
    setNote("Mailbox disconnected. What was already read stays in your books.");
    await load();
    setBusy("");
  };

  if (!state) return null;

  return (
    <div className="card">
      <h3>Connect your mailbox</h3>

      {!state.available ? (
        <p className="muted" style={{ marginBottom: 0 }}>
          {state.detail}
        </p>
      ) : (
        <>
          <p className="muted">{state.detail}</p>

          {state.accounts.map((a) => (
            <div className="row" key={a.id}>
              <div>
                <div style={{ fontWeight: 600, wordBreak: "break-all" }}>{a.email}</div>
                <div className="muted">
                  {a.status === "revoked"
                    ? "Stopped syncing — connect again"
                    : a.last_checked_at
                      ? `Last checked ${new Date(a.last_checked_at).toLocaleString("en-IN", {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })}`
                      : "Waiting for the first check"}
                </div>
              </div>
              <button
                onClick={() => disconnect(a.id)}
                disabled={busy === a.id}
              >
                {busy === a.id ? "…" : "Disconnect"}
              </button>
            </div>
          ))}

          <div className="actions" style={{ marginTop: 12 }}>
            <button className="primary" onClick={connect} disabled={busy === "connect"}>
              {busy === "connect"
                ? "Opening…"
                : state.accounts.length
                  ? "Connect another"
                  : "Connect a mailbox"}
            </button>
            {state.accounts.length > 0 && (
              <button onClick={pull} disabled={busy === "sync"}>
                {busy === "sync" ? "Checking…" : "Check now"}
              </button>
            )}
          </div>

          {note && (
            <p className="muted" style={{ marginBottom: 0 }}>
              {note}
            </p>
          )}

          <p className="muted" style={{ marginBottom: 0, marginTop: 12 }}>
            Longbook only reads your mail. It never sends anything from your
            account, and you can disconnect at any time.
          </p>
        </>
      )}
    </div>
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
