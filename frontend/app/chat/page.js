"use client";

import { useEffect, useRef, useState } from "react";
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
  const bottom = useRef(null);

  useEffect(() => {
    api.chatSuggestions().then((s) => setSuggestions(s.questions)).catch(() => {});
  }, []);

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
    const history = turns.map((t) => ({ role: t.role, text: t.text }));
    setTurns((t) => [...t, { role: "you", text: asked }]);
    setBusy(true);
    try {
      const body = await api.ask(asked, history);
      setTurns((t) => [
        ...t,
        {
          role: "answer",
          text: body.answer,
          answered: body.answered,
          sources: body.sources || [],
          latency_ms: body.latency_ms,
          cost_usd: body.cost_usd,
        },
      ]);
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
          cost_usd: body.cost_usd,
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

            {/* On demand, so the cost of asking should be visible. */}
            <div className="answer-meta">
              {turn.latency_ms != null && `${(turn.latency_ms / 1000).toFixed(1)}s`}
              {turn.cost_usd != null &&
                ` · $${turn.cost_usd < 0.01 ? turn.cost_usd.toFixed(4) : turn.cost_usd.toFixed(2)}`}
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
          <button className="link-button" onClick={() => setTurns([])}>
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
  return (
    <div className="sources">
      <button
        className="sources-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? "Hide" : "Show"} the {rows.length} record
        {rows.length === 1 ? "" : "s"} behind this
      </button>

      {open &&
        rows.map((s) => {
          const href = s.order_id
            ? `/orders/${s.order_id}`
            : s.party_id
              ? `/parties/${s.party_id}`
              : null;
          const inner = (
            <>
              <span className="ref">[{s.ref}]</span>
              <span>
                <strong>{s.label}</strong>
                {s.detail ? <span className="source-detail">{s.detail}</span> : null}
              </span>
            </>
          );
          return href ? (
            <Link href={href} className="source-row" key={s.ref}>
              {inner}
            </Link>
          ) : (
            <div className="source-row" key={s.ref}>
              {inner}
            </div>
          );
        })}
    </div>
  );
}
