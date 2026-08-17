"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api, formatNumber } from "../lib/api";
import Empty from "../components/Empty";
import FilePicker from "../components/FilePicker";
import VoiceNote from "../components/VoiceNote";
import { CHAT_ACCEPT, DEVICE_ACCEPT, IMAGE_ACCEPT } from "../lib/accept";

export default function AddDataPage() {
  return (
    <TokenGate>
      <AddData />
    </TokenGate>
  );
}

// Ordered by what each source keeps doing after today, not by how easy it is
// to build. Email connects once and then stays current on its own, so it goes
// first — it is the only one here that makes the books keep up without anyone
// returning to this screen. Files come next: a Tally export or a folder of
// bills is the fastest way to put real history in on day one.
//
// WhatsApp is last on purpose, and it is the one that most needs its position
// explained. An export is a snapshot: it carries the history well and then
// stops, so a business that set itself up from chat exports alone is a
// business quietly running on last month's information. Until live chat sync
// exists it stays available and stays at the end.
const SOURCES = [
  { key: "email", label: "Email" },
  { key: "upload", label: "Files" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "camera", label: "Photo" },
  { key: "voice", label: "Speak" },
];

function AddData() {
  const [tab, setTab] = useState("email");
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
        <div className="sub">
          Start with email — it keeps itself current. The rest fills in your history.
        </div>
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

      {tab === "email" && <Accounts />}
      {tab === "upload" && <Picker onDone={load} />}
      {tab === "whatsapp" && <Picker mode="whatsapp" onDone={load} />}
      {tab === "camera" && <Picker mode="camera" onDone={load} />}
      {tab === "voice" && <Voice onDone={load} />}

      <History rows={history} />
    </>
  );
}


// What each upload mode offers. Only the input's attributes and the words
// around it change — the parse, estimate and dedup path behind all three is
// identical, deliberately: two ingestion routes would drift apart and one of
// them would quietly stop deduping.
const MODES = {
  files: {
    id: "files",
    label: "Choose files",
    accept: DEVICE_ACCEPT,
    hint:
      "Tally exports, PDFs, bills, sheets, photos or voice notes. Pick as " +
      "many as you like.",
  },
  camera: {
    id: "shot",
    label: "Photograph a bill, challan or ledger page",
    accept: IMAGE_ACCEPT,
    capture: "environment",
    hint:
      "Take as many as you like. Photograph the whole page, straight on, in " +
      "good light — the text is read from the picture.",
  },
  whatsapp: {
    id: "chat",
    // Exports arrive as .txt, or .zip when media came along.
    accept: CHAT_ACCEPT,
    label: "Choose exported chats",
    hint: "One file per chat. Export as many chats as you like and add them together.",
  },
};

function Picker({ mode = "files", onDone }) {
  const cfg = MODES[mode] || MODES.files;
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

      {mode === "whatsapp" && (
        <div className="card">
          <h3>Bring your chat history in</h3>
          {/* Said plainly rather than buried, because it is the one thing that
              decides whether somebody relies on this alone. */}
          <p className="muted">
            An export is a snapshot, not a connection — it carries everything
            said up to today and then stops. Connect your email as well, so the
            books keep up on their own.
          </p>
          <ol style={{ paddingLeft: 18, lineHeight: 1.7, margin: "12px 0 0" }}>
            <li>Open the chat in WhatsApp.</li>
            <li>Tap the name at the top, then scroll to <b>Export chat</b>.</li>
            <li>
              Choose <b>Include media</b> if the chat has photos of bills or
              challans in it — those are read too.
            </li>
            <li>Save the file to this device, then choose it below.</li>
          </ol>
          <div className="row" style={{ marginTop: 12 }}>
            <div>
              <div style={{ fontWeight: 600 }}>WhatsApp Business sync</div>
              <div className="muted">
                Continuous, so you stop exporting chats by hand.
              </div>
            </div>
            <span className="chip plain">Coming soon</span>
          </div>
        </div>
      )}

      <FilePicker
        key={`${mode}-${nonce}`}
        id={cfg.id}
        label={cfg.label}
        accept={cfg.accept}
        capture={cfg.capture}
        hint={cfg.hint}
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
