"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import Dictate from "../components/Dictate";
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

  return (
    <>
      <header className="bar">
        <h1>ASK</h1>
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
            You can ask anything about your business. Example questions:
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

      {/* One bar, always. Speaking used to replace it with a recording panel,
          which meant the question you had half-typed vanished and what came
          back was an answer rather than words you could fix. Now the mic
          dictates into the same box the keyboard fills. */}
      <div className="ask-bar">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask()}
          placeholder="Who owes me the most?"
          aria-label="Your question"
        />
        {/* Both are plain icons on the bar. They were buttons carrying their
            own borders and fills, which put three rectangles inside one. */}
        <Dictate
          onText={(t) => setQuestion((q) => (q ? `${q} ${t}` : t))}
          onError={setError}
        />
        <button
          className="send"
          disabled={busy || !question.trim()}
          onClick={() => ask()}
          aria-label="Send"
          title="Send"
        >
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
               fill="none" stroke="currentColor" strokeWidth="2"
               strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 12h14" />
            <path d="M13 6l6 6-6 6" />
          </svg>
        </button>
      </div>

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
