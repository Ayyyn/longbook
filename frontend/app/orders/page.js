"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "../components/TokenGate";
import { api, formatNumber } from "../lib/api";
import Empty, { SetupIncomplete, BackfillProgress } from "../components/Empty";

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
  const [job, setJob] = useState(null);
  const [setup, setSetup] = useState(false);

  const load = useCallback(async (which) => {
    const running = await api.latestJob().catch(() => null);
    setJob(running);
    try {
      setData(await api.orders({ status: which }));
      setSetup(false);
      setError(null);
    } catch (err) {
      setData({ orders: [], total: 0, by_status: {} });
      if (err.status === 409) setSetup(true);
      else setError(err.message);
    }
  }, []);

  useEffect(() => {
    load(status);
  }, [load, status]);

  const working = job && job.state !== "done" && job.state !== "failed";

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

      {setup ? (
        working ? <BackfillProgress job={job} /> : <SetupIncomplete />
      ) : !data ? (
        <div className="empty">Loading…</div>
      ) : data.orders.length === 0 ? (
        status ? (
          <Empty title={`No ${FILTERS.find((f) => f.key === status)?.label.toLowerCase()} orders`}>
            Nothing is at this stage right now. Try “All” to see every order.
          </Empty>
        ) : working ? (
          <BackfillProgress job={job} />
        ) : (
          <Empty title="No orders yet">
            Orders are written automatically when someone asks for goods in
            WhatsApp — quality, quantity and rate, taken from the message.
            None have been found yet.
          </Empty>
        )
      ) : (
        data.orders.map((o) => (
          <Link key={o.id} href={`/orders/${o.id}`} className="list-row">
            <div className="top">
              <span className="name">{o.party_name || "Unknown party"}</span>
              <span className="muted" style={{ fontSize: 14 }}>
                {o.order_date || ""}
              </span>
            </div>
            <div className="sub">
              {o.order_no ? `${o.order_no} · ` : ""}
              {formatNumber(o.lines)} line{o.lines === 1 ? "" : "s"}
              {o.promised_date ? ` · due ${o.promised_date}` : ""}
            </div>
            <div style={{ marginTop: 8 }}>
              {o.pending_fields?.length > 0 ? (
                <span className="pending-tag">needs {o.pending_fields.length}</span>
              ) : (
                <span className={`badge-status ${o.status}`}>{o.status}</span>
              )}
            </div>
          </Link>
        ))
      )}
    </>
  );
}
