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
        <span className={`badge-status ${order.status}`}>{order.status}</span>
        {order.pending_fields?.length > 0 && (
          <span className="chip">needs {order.pending_fields.join(", ")}</span>
        )}
      </div>

      <div className="card">
        {order.lines.length === 0 ? (
          <p className="muted">No lines recorded.</p>
        ) : (
          <table className="items">
            <thead>
              <tr>
                <th>Item</th>
                <th>Qty</th>
                <th>Rate</th>
                <th>Amount</th>
              </tr>
            </thead>
            <tbody>
              {order.lines.map((line, i) => (
                <tr key={i}>
                  <td>
                    {line.quality || "—"}
                    {line.unit ? <span className="muted"> ({line.unit})</span> : null}
                  </td>
                  <td>{line.quantity != null ? formatNumber(line.quantity) : "—"}</td>
                  <td>{line.rate != null ? formatNumber(line.rate) : "—"}</td>
                  <td>
                    {line.quantity != null && line.rate != null
                      ? formatNumber(line.quantity * line.rate)
                      : "—"}
                  </td>
                </tr>
              ))}
              {order.value > 0 && (
                <tr className="total">
                  <td colSpan={3}>Total amount</td>
                  <td>{money(order.value)}</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {order.timeline?.length > 0 && (
        <div className="card">
          <h3>Status</h3>
          <div className="timeline">
            {order.timeline.map((t, i) => (
              <div className="step" key={i}>
                <span className="when">{t.when}</span>
                <span>{t.what}</span>
              </div>
            ))}
          </div>
        </div>
      )}

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
            <div className={`bubble${m.cited ? " cited" : ""}`} key={m.id}>
              <span className="who">
                {m.sender}
                {m.occurred_at
                  ? ` · ${new Date(m.occurred_at).toLocaleDateString("en-IN")}`
                  : ""}
              </span>
              {m.body}
            </div>
          ))}
          <p className="muted" style={{ marginTop: 12, marginBottom: 0 }}>
            Outlined messages are the ones this order was read from.
          </p>
        </div>
      )}

      {order.dispatch && (
        <div className="card">
          <h3>Dispatch details</h3>
          {[
            ["Challan no", order.dispatch.challan_no],
            ["Transporter", order.dispatch.transporter],
            ["LR number", order.dispatch.lr_no],
          ]
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div className="row" key={k}>
                <div className="muted">{k}</div>
                <div style={{ fontWeight: 600 }}>{v}</div>
              </div>
            ))}
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
