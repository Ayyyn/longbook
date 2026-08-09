"use client";

import Link from "next/link";

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
export function SetupIncomplete() {
  return (
    <Empty title="Setup isn't finished">
      Your business is created, but no WhatsApp history has been read yet.
      Send your chat export to whoever set this up for you — orders,
      payments and parties all come from it. This screen fills in on its own
      once that is done.
    </Empty>
  );
}

// Shown while the backfill is working. It reports what has actually landed
// rather than a spinner: an owner who just handed over six years of history
// wants to watch it arrive.
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

  return (
    <div className="empty-state working">
      <h3>Reading your WhatsApp history…</h3>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="why">
        {`${done} of ${total} messages read`}
        {written > 0 ? ` · ${written} records found so far` : ""}
      </div>
      <p className="muted" style={{ marginBottom: 0 }}>
        This takes a few minutes for a long history. You can leave this screen
        and come back — it keeps running.
      </p>
    </div>
  );
}
