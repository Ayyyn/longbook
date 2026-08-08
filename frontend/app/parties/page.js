"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api, money } from "../lib/api";

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

  const load = useCallback(async (q, which) => {
    try {
      setData(
        await api.parties({
          q,
          overdueOnly: which === "overdue",
          hasOutstanding: which === "outstanding",
        })
      );
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    // Debounced so typing a name does not fire a request per keystroke on a
    // market-grade connection.
    const timer = setTimeout(() => load(query, filter), query ? 300 : 0);
    return () => clearTimeout(timer);
  }, [load, query, filter]);

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

      {!data ? (
        <div className="empty">Loading…</div>
      ) : data.parties.length === 0 ? (
        <div className="empty">
          {query ? `Nobody matching “${query}”.` : "No parties yet."}
        </div>
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
