"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api } from "../lib/api";

export default function BusinessPage() {
  return (
    <TokenGate>
      <About />
    </TokenGate>
  );
}

// The one screen that answers "what does this thing think my business is?".
//
// It deliberately does not require onboarding to have finished. The business
// that uploaded one file, answered two questions and stopped is exactly the
// one whose owner needs to see where they got to — and until now that state
// was invisible from inside the app, which is how someone ends up staring at
// a progress bar that will never move.
function About() {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({});
  const [basics, setBasics] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const body = await api.business();
      setData(body);
      setDraft(
        Object.fromEntries(body.answers.map((a) => [a.question, a.answer || ""])),
      );
      setBasics(body.basics || {});
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Only what actually changed goes up, so an untouched field can never
  // overwrite a good answer with an empty string.
  const changed = data
    ? Object.fromEntries(
        data.answers
          .filter((a) => (draft[a.question] || "") !== (a.answer || ""))
          .map((a) => [a.question, draft[a.question] || ""]),
      )
    : {};
  const dirty = Object.keys(changed).length > 0;

  async function save(reconfigure) {
    setSaving(true);
    setError(null);
    try {
      const body = await api.updateBusiness({
        answers: changed,
        basics,
        reconfigure,
      });
      setData(body);
      setDraft(
        Object.fromEntries(body.answers.map((a) => [a.question, a.answer || ""])),
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 4000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (error && !data) return <div className="banner error">{error}</div>;
  if (!data) return <div className="empty-state"><h3>Loading…</h3></div>;

  const universal = data.answers.filter((a) => a.stage === "universal");
  const generated = data.answers.filter((a) => a.stage !== "universal");
  const units = data.vocabulary?.quantity_units || [];

  return (
    <>
      <header className="bar">
        <h1>About the business</h1>
        <div className="sub">
          What we asked, what you told us, and what we made of it
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}
      {saved && <div className="banner">Saved.</div>}

      {!data.configured && (
        <div className="banner warn">
          <strong>Setup was never finished.</strong> Your answers are kept here,
          but nothing is being read yet and no records are being created.
          Finish setup and the reading starts.{" "}
          <Link href="/signup">Finish setup</Link>
        </div>
      )}

      {data.answers.length === 0 ? (
        <div className="empty-state">
          <h3>Nothing asked yet</h3>
          <div className="why">
            The questions are written after we have seen some of your records —
            they are about what is actually in them, so there is nothing to ask
            until something has been added.
          </div>
          <Link href="/add" className="button-link">
            <button className="primary">Add your data</button>
          </Link>
        </div>
      ) : (
        <>
          {universal.length > 0 && (
            <section className="feed">
              <h2>The basics</h2>
              {universal.map((a) => (
                <Answer
                  key={a.question}
                  row={a}
                  value={draft[a.question] ?? ""}
                  onChange={(v) => setDraft((d) => ({ ...d, [a.question]: v }))}
                />
              ))}
            </section>
          )}

          {generated.length > 0 && (
            <section className="feed">
              <h2>Asked about your own records</h2>
              <p className="muted" style={{ margin: "0 0 12px" }}>
                These were written for your business after reading what you
                sent — another trade gets different questions.
              </p>
              {generated.map((a) => (
                <Answer
                  key={a.question}
                  row={a}
                  value={draft[a.question] ?? ""}
                  onChange={(v) => setDraft((d) => ({ ...d, [a.question]: v }))}
                />
              ))}
            </section>
          )}

          <div className="actions">
            <button
              className="primary"
              disabled={saving || !dirty}
              onClick={() => save(false)}
            >
              {saving ? "Saving…" : dirty ? "Save changes" : "No changes"}
            </button>
          </div>
          <p className="muted">
            Saving keeps your answers. To rebuild how the system reads your
            records from them — units, thresholds, which screens are on — use
            the button below. It does not re-read anything you have already
            added.
          </p>
          <div className="actions">
            <button disabled={saving} onClick={() => save(true)}>
              {saving ? "Working…" : "Save and rebuild the setup"}
            </button>
          </div>
        </>
      )}

      {data.observations?.length > 0 && (
        <section className="feed">
          <h2>What we noticed in your records</h2>
          <div className="card">
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {data.observations.map((o, i) => (
                <li key={i} style={{ marginBottom: 8, lineHeight: 1.6 }}>
                  {o}
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {data.configured && (
        <section className="feed">
          <h2>What the system decided</h2>
          <div className="card">
            <div className="row">
              <span>Your words for things</span>
              <strong>
                {units.length ? units.join(", ") : "not set"}
              </strong>
            </div>
            <div className="row">
              <span>Credit terms used for overdue</span>
              <strong>{data.rules?.overdue_days ?? "—"} days</strong>
            </div>
            <div className="row">
              <span>Flag a rate that differs by more than</span>
              <strong>{data.rules?.rate_deviation_pct ?? "—"}%</strong>
            </div>
            <div className="row">
              <span>Screens switched on</span>
              <strong>
                {Object.entries(data.modules || {})
                  .filter(([, on]) => on)
                  .map(([k]) => k.replace(/_/g, " "))
                  .join(", ") || "the basics only"}
              </strong>
            </div>
            <div className="row">
              <span>Setup version</span>
              <strong>{data.version}</strong>
            </div>
          </div>
        </section>
      )}
    </>
  );
}

function Answer({ row, value, onChange }) {
  return (
    <div className="card">
      <label htmlFor={row.question} style={{ textTransform: "none", fontSize: 15 }}>
        {row.question}
      </label>
      {row.hint && (
        <p className="muted" style={{ margin: "0 0 8px" }}>
          {row.hint}
        </p>
      )}
      <textarea
        id={row.question}
        rows={2}
        value={value}
        placeholder="Not answered"
        onChange={(e) => onChange(e.target.value)}
        style={{ width: "100%" }}
      />
    </div>
  );
}
