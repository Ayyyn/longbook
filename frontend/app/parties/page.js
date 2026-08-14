"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api, money } from "../lib/api";
import Empty, { SetupIncomplete, BackfillProgress } from "../components/Empty";

export default function PartiesPage() {
  return (
    <TokenGate>
      <Parties />
    </TokenGate>
  );
}

function Parties() {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState(null);
  const [job, setJob] = useState(null);
  const [setup, setSetup] = useState(false);

  const load = useCallback(async (q, which) => {
    const running = await api.latestJob().catch(() => null);
    setJob(running);
    try {
      setData(
        await api.parties({
          q,
          overdueOnly: which === "overdue",
          hasOutstanding: which === "outstanding",
        })
      );
      setSetup(false);
      setError(null);
    } catch (err) {
      // Without this the screen kept "Loading…" on screen forever, because
      // `data` never arrived and nothing else claimed the empty slot.
      setData({ parties: [], total: 0, total_outstanding: 0 });
      if (err.status === 409) setSetup(true);
      else setError(err.message);
    }
  }, []);

  useEffect(() => {
    // Debounced so typing a name does not fire a request per keystroke on a
    // market-grade connection.
    const timer = setTimeout(() => load(query, filter), query ? 300 : 0);
    return () => clearTimeout(timer);
  }, [load, query, filter]);

  // setup_required means the messages are held but nothing can read them
  // until the interview is answered — the opposite of "in progress".
  const blocked = job?.state === "setup_required";
  const working =
    job && !blocked && job.state !== "done" && job.state !== "failed";

  return (
    <>
      <header className="bar">
        <h1>Parties</h1>
        {data && (
          <div className="sub">
            {data.total} {data.total === 1 ? "party" : "parties"} ·{" "}
            {money(data.total_outstanding)} outstanding
          </div>
        )}
      </header>

      {error && <div className="banner error">{error}</div>}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search name or phone"
        autoComplete="off"
        style={{ marginTop: 12 }}
      />

      <div className="filters">
        {[
          { key: "all", label: "All" },
          { key: "outstanding", label: "Has outstanding" },
          { key: "overdue", label: "Overdue" },
        ].map((f) => (
          <button
            key={f.key}
            className={filter === f.key ? "primary" : ""}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {setup ? (
        <SetupIncomplete />
      ) : !data ? (
        <div className="empty">Loading…</div>
      ) : data.parties.length === 0 ? (
        query ? (
          <Empty title={`Nobody matching “${query}”`}>
            Parties are named as they appear in your chats. Try a shorter
            spelling, or part of the phone number.
          </Empty>
        ) : blocked ? (
          <SetupIncomplete held={job.total} />
        ) : working ? (
          <BackfillProgress job={job} />
        ) : (
          <Empty title="No parties yet">
            Every customer and supplier here is created automatically from your
            WhatsApp history — who they are, what they buy, and what they owe.
            None have been found yet.
          </Empty>
        )
      ) : (
        data.parties.map((p) => (
          <Link
            key={p.id}
            href={`/parties/${p.id}`}
            className={`list-row${p.is_overdue ? " overdue" : ""}`}
          >
            <div className="top">
              <span className="name">{p.name}</span>
              <span className="amount">{p.outstanding ? money(p.outstanding) : "—"}</span>
            </div>
            <div className="sub">{p.summary}</div>
          </Link>
        ))
      )}
    </>
  );
}
