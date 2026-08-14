"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { api } from "../lib/api";

// Empty screens are the first thing a new owner sees, and "No data" tells them
// nothing they did not already know. Every empty state here answers the same
// two questions: why is this blank, and what happens next.
export default function Empty({ title, children, action, href, onAction }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <div className="why">{children}</div>
      {href && action && (
        <Link href={href} className="button-link">
          <button className="primary">{action}</button>
        </Link>
      )}
      {onAction && action && (
        <button className="primary" onClick={onAction}>
          {action}
        </button>
      )}
    </div>
  );
}

// The one an owner hits before their export has ever been processed. The API
// answers 409 until a BusinessProfile exists; that is a setup step, not an
// error, and it must never reach the screen as one.
export function SetupIncomplete({ held = 0 }) {
  // Two different situations wear the same title. Nothing uploaded is a
  // "go and add something" problem. Something uploaded but no profile is the
  // worse one: the owner has already done the work, is owed an explanation of
  // why nothing is happening, and needs the way back into the interview —
  // which is not obvious, because signup looks like a thing you only do once.
  if (held > 0) {
    return (
      <Empty title="Setup isn't finished" action="Finish setup" href="/signup">
        {held} {held === 1 ? "item is" : "items are"} saved and waiting, but
        nothing is being read yet. Longbook needs a few answers about your
        business first — it reads your records against how <em>you</em> work,
        so it cannot start until it knows that. It takes about five minutes,
        and everything you have already added is picked up straight after.
      </Empty>
    );
  }
  return (
    <Empty title="Setup isn't finished" action="Add your data" href="/add">
      Your business is created, but nothing has been read yet. Add a WhatsApp
      chat export, a Tally or Excel party list, or a photo of a bill — orders,
      payments and parties all come from those. This screen fills in on its
      own once something has been read.
    </Empty>
  );
}

// Shown while the backfill is working. It reports what has actually landed
// rather than a spinner: an owner who just handed over six years of history
// wants to watch it arrive.
// How long progress may sit still before we stop calling it "reading". The
// backfill is paced to ~10 model calls a minute, so a genuinely healthy run
// moves well inside this; longer than this means the container that was doing
// the work is gone.
const STALL_MS = 120_000;

export function BackfillProgress({ job }) {
  // Messages, not conversation windows. windows_* come from a per-process
  // registry, and Cloud Run answers this poll from whichever instance is free
  // — usually not the one running the backfill — so they arrive as zero and
  // the bar would sit empty while the count underneath climbed. processed and
  // total are counted from the database and are the same on every instance.
  const total = job.total || 0;
  const done = job.processed || 0;
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const written = (job.committed || 0) + (job.needs_review || 0);

  // Watch the count rather than the clock: the parent re-polls every few
  // seconds, so a `processed` that never changes is the only reliable signal
  // that the work has stopped.
  const seen = useRef({ done, at: Date.now() });
  const [stalled, setStalled] = useState(false);
  const [resuming, setResuming] = useState(false);

  useEffect(() => {
    if (done !== seen.current.done) {
      seen.current = { done, at: Date.now() };
      setStalled(false);
      return undefined;
    }
    const timer = setTimeout(
      () => setStalled(Date.now() - seen.current.at >= STALL_MS),
      STALL_MS,
    );
    return () => clearTimeout(timer);
  }, [done, job]);

  if (stalled) {
    return (
      <div className="empty-state working">
        <h3>Reading paused</h3>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="why">
          {done} of {total} messages read
          {written > 0 ? ` · ${written} records found so far` : ""}. Reading
          stopped before it finished — nothing has been lost, and picking it up
          again only costs the messages still left.
        </div>
        <button
          className="primary"
          disabled={resuming}
          onClick={async () => {
            setResuming(true);
            try {
              await api.resumeBackfill();
              seen.current = { done, at: Date.now() };
              setStalled(false);
            } finally {
              setResuming(false);
            }
          }}
        >
          {resuming ? "Starting…" : "Carry on reading"}
        </button>
      </div>
    );
  }

  return (
    <div className="empty-state working">
      <h3>Reading what you sent…</h3>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="why">
        {`${done} of ${total} ${total === 1 ? "item" : "items"} read`}
        {written > 0 ? ` · ${written} records found so far` : ""}
      </div>
      <p className="muted" style={{ marginBottom: 0 }}>
        This takes a few minutes for a long history. You can leave this screen
        and come back — it keeps running.
      </p>
    </div>
  );
}
