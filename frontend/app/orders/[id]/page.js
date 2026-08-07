"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import TokenGate from "../../components/TokenGate";
import { api, money, formatNumber } from "../../lib/api";

export default function OrderDetailPage() {
  return (
    <TokenGate>
      <OrderDetail />
    </TokenGate>
  );
}

function OrderDetail() {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setOrder(await api.order(id));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <>
        <Link href="/orders" className="back">← Orders</Link>
        <div className="banner error">{error}</div>
      </>
    );
  }
  if (!order) return <div className="empty">Loading…</div>;

  return (
    <>
      <Link href="/orders" className="back">← Orders</Link>

      <header className="bar">
        <h1>{order.order_no || "Order"}</h1>
        <div className="sub">
          {order.party_name || "Unknown party"}
          {order.order_date ? ` · ${order.order_date}` : ""}
        </div>
      </header>

      <div className="chips">
        <span className="chip plain">{order.status}</span>
        {order.dispatched && <span className="chip plain">dispatched</span>}
        {order.pending_fields?.length > 0 && (
          <span className="chip">needs {order.pending_fields.join(", ")}</span>
        )}
      </div>

      <div className="card">
        <h3>Items</h3>
        {order.lines.length === 0 ? (
          <p className="muted">No lines recorded.</p>
        ) : (
          order.lines.map((line, i) => (
            <div className="row" key={i}>
              <div>
                <div>{line.quality || "—"}</div>
                <div className="muted">
                  {line.quantity != null ? formatNumber(line.quantity) : "—"}
                  {line.unit ? ` ${line.unit}` : ""}
                  {line.rate != null ? ` @ ${money(line.rate)}` : ""}
                </div>
              </div>
              <div style={{ fontWeight: 650 }}>
                {line.quantity != null && line.rate != null
                  ? money(line.quantity * line.rate)
                  : "—"}
              </div>
            </div>
          ))
        )}
        {order.value > 0 && (
          <div className="row" style={{ borderTop: "2px solid var(--line)" }}>
            <div style={{ fontWeight: 650 }}>Total</div>
            <div style={{ fontWeight: 650 }}>{money(order.value)}</div>
          </div>
        )}
      </div>

      {order.promised_date && (
        <p className="muted">Promised by {order.promised_date}.</p>
      )}
      {order.notes && <div className="card">{order.notes}</div>}

      {/* Where this came from — the messages the record was drawn from, with
          the cited lines marked. Owners check these against Tally. */}
      {order.conversation?.length > 0 && (
        <div className="know">
          <h3>Where this came from</h3>
          {order.conversation.map((m) => (
            <div className={`msg-line${m.cited ? " cited" : ""}`} key={m.id}>
              <span className="who">
                {m.sender}
                {m.occurred_at
                  ? ` · ${new Date(m.occurred_at).toLocaleDateString("en-IN")}`
                  : ""}
              </span>
              {m.body}
            </div>
          ))}
          <p className="muted" style={{ marginTop: 10, marginBottom: 0 }}>
            Highlighted lines are the ones this order was read from.
          </p>
        </div>
      )}

      {order.party_id && (
        <div className="actions">
          <Link href={`/parties/${order.party_id}`} style={{ flex: 1 }}>
            <button style={{ width: "100%" }}>Open {order.party_name}</button>
          </Link>
        </div>
      )}
    </>
  );
}
