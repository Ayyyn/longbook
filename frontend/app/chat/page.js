"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import VoiceNote from "../components/VoiceNote";
import AnswerBody from "../components/AnswerBody";
import { api, formatNumber } from "../lib/api";

export default function ChatPage() {
  return (
    <TokenGate>
      <Chat />
    </TokenGate>
  );
}

function Chat() {
  const [turns, setTurns] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [mic, setMic] = useState(false);
  const [error, setError] = useState(null);
  const [conversationId, setConversationId] = useState(null);
  const [past, setPast] = useState([]);
  const [showPast, setShowPast] = useState(false);
  const bottom = useRef(null);

  useEffect(() => {
    api.chatSuggestions().then((s) => setSuggestions(s.questions)).catch(() => {});
  }, []);

  const loadPast = useCallback(async () => {
    setPast(await api.conversations().catch(() => []));
  }, []);
  useEffect(() => {
    loadPast();
  }, [loadPast]);

  // Opening an old thread replaces what is on screen, citations and all —
  // the answers were stored with their sources, so the proof survives too.
  async function open(id) {
    setShowPast(false);
    setError(null);
    try {
      const stored = await api.conversation(id);
      setTurns(stored.map((t) => ({
        role: t.role,
        text: t.text,
        answered: t.answered,
        sources: t.sources || [],
        latency_ms: t.latency_ms,
      })));
      setConversationId(id);
    } catch (err) {
      setError(err.message);
    }
  }

  function startNew() {
    setTurns([]);
    setConversationId(null);
    setShowPast(false);
  }

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  async function ask(text) {
    const asked = (text ?? question).trim();
    if (!asked || busy) return;
    setQuestion("");
    setError(null);
    // The history sent is what is on screen, so follow-ups like "what about
    // last year" resolve against what was actually said.
    // Sent only for a brand new thread; once it has an id the server owns the
    // history, which is what lets the same thread continue on another device.
    const history = conversationId
      ? []
      : turns.map((t) => ({ role: t.role, text: t.text }));
    setTurns((t) => [...t, { role: "you", text: asked }]);
    setBusy(true);
    try {
      const body = await api.ask(asked, conversationId, history);
      setTurns((t) => [
        ...t,
        {
          role: "answer",
          text: body.answer,
          answered: body.answered,
          sources: body.sources || [],
          latency_ms: body.latency_ms,
        },
      ]);
      if (body.conversation_id) {
        setConversationId(body.conversation_id);
        loadPast();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function askByVoice(file) {
    setMic(false);
    setBusy(true);
    setError(null);
    setTurns((t) => [...t, { role: "you", text: "🎤 Voice question" }]);
    try {
      const body = await api.askVoice(file);
      setTurns((t) => [
        ...t,
        {
          role: "answer",
          text: body.answer,
          answered: body.answered,
          sources: body.sources || [],
          latency_ms: body.latency_ms,
          heard: body.question,
        },
      ]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="bar">
        <h1>Ask</h1>
        <div className="sub">Questions about your own records, with the proof</div>
      </header>

      {past.length > 0 && (
        <div className="chat-history">
          <button className="link-button" onClick={() => setShowPast((v) => !v)}>
            {showPast ? "Hide" : "Earlier questions"} ({past.length})
          </button>
          {turns.length > 0 && (
            <button className="link-button" onClick={startNew}>
              New question
            </button>
          )}
        </div>
      )}

      {showPast && (
        <div className="card">
          {past.map((c) => (
            <div className="row" key={c.id}>
              <button
                className="link-button"
                style={{ textAlign: "left" }}
                onClick={() => open(c.id)}
              >
                {c.title || "Untitled"}
              </button>
              <button
                className="link-button"
                aria-label="Delete this conversation"
                onClick={async () => {
                  await api.deleteConversation(c.id).catch(() => {});
                  if (c.id === conversationId) startNew();
                  loadPast();
                }}
              >
                Delete
              </button>
            </div>
          ))}
        </div>
      )}

      {error && <div className="banner error">{error}</div>}

      {turns.length === 0 && (
        <div className="empty-state" style={{ textAlign: "left" }}>
          <h3>What would you like to know?</h3>
          <div className="why">
            I answer only from your own records, and I show you which record
            each answer came from. If I do not have it, I will say so rather
            than guess.
          </div>
          <div className="suggestions">
            {suggestions.map((s) => (
              <button key={s} onClick={() => ask(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {turns.map((turn, i) =>
        turn.role === "you" ? (
          <div className="bubble mine" key={i}>
            {turn.text}
          </div>
        ) : (
          <div className="answer-card" key={i}>
            {turn.heard && (
              <p className="muted" style={{ marginTop: 0 }}>
                Heard: “{turn.heard}”
              </p>
            )}
            <AnswerBody text={turn.text} />

            {turn.sources?.length > 0 && <Sources rows={turn.sources} />}

            {!turn.answered && turn.sources?.length === 0 && (
              <p className="muted" style={{ marginBottom: 0 }}>
                Nothing on record answers this yet.{" "}
                <Link href="/add">Add more data</Link>.
              </p>
            )}

            {/* What it cost us to answer is our business, not the owner's.
                It is still recorded on every agent_run — the accounting has
                not changed, only who is shown it. A shopkeeper asking where
                their money is should not be reading a meter while they do it. */}
            <div className="answer-meta">
              {turn.latency_ms != null && `${(turn.latency_ms / 1000).toFixed(1)}s`}
            </div>
          </div>
        ),
      )}

      {busy && <div className="bubble">Looking through your records…</div>}
      <div ref={bottom} />

      {mic ? (
        <VoiceNote
          label="Ask out loud"
          hint="Hindi, Gujarati, Marathi or English — or all three."
          onRecorded={askByVoice}
        />
      ) : (
        <div className="ask-bar">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            placeholder="Who owes me the most?"
            aria-label="Your question"
          />
          <button
            className="mic-btn"
            aria-label="Ask by voice"
            onClick={() => setMic(true)}
          >
            🎤
          </button>
          <button className="primary" disabled={busy || !question.trim()} onClick={() => ask()}>
            Ask
          </button>
        </div>
      )}

      {turns.length > 0 && (
        <p className="muted" style={{ textAlign: "center" }}>
          <button className="link-button" onClick={startNew}>
            Start again
          </button>
          {" · "}
          {formatNumber(turns.filter((t) => t.role === "you").length)} asked
        </p>
      )}
    </>
  );
}

// Citations, folded away.
//
// They were printed in full under every answer: nine rows of "name: X, kind:
// customer, credit_days: 0" and 400-character chat excerpts, which buried a
// two-line answer under a page of evidence nobody had asked to read yet.
//
// The proof still has to be one tap away — that is the product's whole claim —
// so the summary line stays visible and says how many records the answer rests
// on. Opening it shows them.
function Sources({ rows }) {
  const [open, setOpen] = useState(false);

  // Records and web pages are both evidence, and the owner has to be able to
  // tell them apart at a glance — trusting the books is the whole proposition,
  // and it survives only if "your ledger says" never blurs into "a website
  // says". So they are counted separately in the summary and marked
  // differently in the list.
  const records = rows.filter((s) => s.kind !== "web");
  const web = rows.filter((s) => s.kind === "web");
  const summary = [
    records.length ? `${records.length} record${records.length === 1 ? "" : "s"}` : null,
    web.length ? `${web.length} web source${web.length === 1 ? "" : "s"}` : null,
  ].filter(Boolean).join(" and ");

  return (
    <div className="sources">
      <button
        className="sources-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide" : "Show"} the {summary} behind this
      </button>

      {open &&
        rows.map((s, i) => {
          const isWeb = s.kind === "web";
          const href = isWeb
            ? s.url
            : s.order_id
              ? `/orders/${s.order_id}`
              : s.party_id
                ? `/parties/${s.party_id}`
                : null;
          const inner = (
            <>
              <span className="ref">{isWeb ? "web" : `[${s.ref}]`}</span>
              <span>
                <strong>{s.label}</strong>
                {s.detail && !isWeb ? (
                  <span className="source-detail">{s.detail}</span>
                ) : null}
              </span>
            </>
          );
          const key = s.ref || s.url || `row-${i}`;
          // An external link leaves the app, so it is a plain anchor rather
          // than a router Link, and carries noopener.
          if (isWeb && href) {
            return (
              <a
                className="source-row"
                key={key}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
              >
                {inner}
              </a>
            );
          }
          return href ? (
            <Link href={href} className="source-row" key={key}>
              {inner}
            </Link>
          ) : (
            <div className="source-row" key={key}>
              {inner}
            </div>
          );
        })}
    </div>
  );
}
