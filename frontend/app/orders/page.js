"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api, formatNumber } from "../lib/api";

const FILTERS = [
  { key: null, label: "All" },
  { key: "draft", label: "To confirm" },
  { key: "confirmed", label: "Confirmed" },
  { key: "dispatched", label: "Dispatched" },
  { key: "closed", label: "Closed" },
];

export default function OrdersPage() {
  return (
    <TokenGate>
      <Orders />
    </TokenGate>
  );
}

function Orders() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async (which) => {
    try {
      setData(await api.orders({ status: which }));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load(status);
  }, [load, status]);

  return (
    <>
      <header className="bar">
        <h1>Orders</h1>
        {data && <div className="sub">{data.total} shown</div>}
      </header>

      {error && <div className="banner error">{error}</div>}

      <div className="filters">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            className={status === f.key ? "primary" : ""}
            onClick={() => setStatus(f.key)}
          >
            {f.label}
            {data?.by_status && f.key && data.by_status[f.key]
              ? ` (${data.by_status[f.key]})`
              : ""}
          </button>
        ))}
      </div>

      {!data ? (
        <div className="empty">Loading…</div>
      ) : data.orders.length === 0 ? (
        <div className="empty">No orders here.</div>
      ) : (
        data.orders.map((o) => (
          <Link key={o.id} href={`/orders/${o.id}`} className="list-row">
            <div className="top">
              <span className="name">{o.party_name || "Unknown party"}</span>
              {o.pending_fields?.length > 0 ? (
                <span className="pending-tag">needs {o.pending_fields.length}</span>
              ) : (
                <span className="muted">{o.status}</span>
              )}
            </div>
            <div className="sub">
              {o.order_no ? `${o.order_no} · ` : ""}
              {formatNumber(o.lines)} line{o.lines === 1 ? "" : "s"}
              {o.order_date ? ` · ${o.order_date}` : ""}
              {o.promised_date ? ` · due ${o.promised_date}` : ""}
            </div>
          </Link>
        ))
      )}
    </>
  );
}
