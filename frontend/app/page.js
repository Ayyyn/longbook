"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "./components/TokenGate";
import { api, money, formatNumber } from "./lib/api";

const LABELS = {
  newly_overdue: "Newly overdue",
  low_stock: "Low stock",
};

export default function TodayPage() {
  return (
    <TokenGate>
      <Today />
    </TokenGate>
  );
}

function Today() {
  const [data, setData] = useState(null);
  const [me, setMe] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [digest, profile] = await Promise.all([api.today(), api.me()]);
      setData(digest);
      setMe(profile);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <Banner message={error} onRetry={load} />;
  if (!data) return <div className="empty">Loading…</div>;

  return (
    <>
      <header className="bar">
        <h1>{me?.business_name || "Today"}</h1>
        <div className="sub">
          {new Date(data.date).toLocaleDateString("en-IN", {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </div>
      </header>

      <div className="stat-grid">
        <div className="stat wide">
          <div className="label">Money in today</div>
          <div className="value">{money(data.money_in.today)}</div>
          <div className="note">
            {data.money_in.payments_today} payment
            {data.money_in.payments_today === 1 ? "" : "s"} · {money(data.money_in.last_7_days)} this
            week
          </div>
        </div>

        <div className={`stat wide${data.overdue.total ? " pending" : ""}`}>
          <div className="label">Overdue</div>
          <div className="value">{money(data.overdue.total)}</div>
          <div className="note">
            {data.overdue.parties ? (
              <Link href="/parties">
                {data.overdue.parties}{" "}
                {data.overdue.parties === 1 ? "party" : "parties"} past{" "}
                {data.overdue.overdue_days} days · worst {data.overdue.worst_party} at{" "}
                {data.overdue.worst_days}d
              </Link>
            ) : (
              `nobody past ${data.overdue.overdue_days} days`
            )}
          </div>
        </div>

        <div className="stat">
          <div className="label">New orders</div>
          <div className="value">{formatNumber(data.orders.new_today)}</div>
          <div className="note">{data.orders.new_last_7_days} this week</div>
        </div>

        <div className="stat">
          <div className="label">Open orders</div>
          <div className="value">{formatNumber(data.orders.open_total)}</div>
          <div className="note">
            <Link href="/orders">{data.orders.awaiting_confirmation} to confirm</Link>
          </div>
        </div>

        <div className="stat">
          <div className="label">Dispatched</div>
          <div className="value">{formatNumber(data.dispatches_today)}</div>
          <div className="note">today</div>
        </div>

        <div className={`stat${data.needs_review ? " pending" : ""}`}>
          <div className="label">To review</div>
          <div className="value">{formatNumber(data.needs_review)}</div>
          <div className="note">
            {data.needs_review ? <Link href="/review">Open the queue</Link> : "all clear"}
          </div>
        </div>
      </div>

      {data.exceptions.total > 0 && (
        <div className="card">
          <h3>Needs a look</h3>
          {data.exceptions.headline && <p style={{ margin: "6px 0" }}>{data.exceptions.headline}</p>}
          <div className="chips">
            {data.exceptions.slowing_payers > 0 && (
              <span className="chip">{data.exceptions.slowing_payers} paying slower</span>
            )}
            {data.exceptions.stalled_orders > 0 && (
              <span className="chip">{data.exceptions.stalled_orders} orders overdue to send</span>
            )}
            {data.exceptions.rate_deviations > 0 && (
              <span className="chip">{data.exceptions.rate_deviations} odd rates</span>
            )}
          </div>
        </div>
      )}

      <div className="card">
        <h3>Recent payments</h3>
        {data.recent_payments.length === 0 ? (
          <p className="muted">Nothing recorded yet.</p>
        ) : (
          data.recent_payments.map((payment) => (
            <div className="row" key={payment.id}>
              <div>
                <div>{payment.party_name || "Unknown party"}</div>
                <div className="muted">
                  {payment.mode || "—"}
                  {payment.received_on ? ` · ${payment.received_on}` : ""}
                </div>
              </div>
              <div style={{ fontWeight: 650 }}>
                {payment.amount == null ? (
                  <span className="pending-tag">amount?</span>
                ) : (
                  money(payment.amount)
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {data.unavailable.length > 0 && (
        <div className="card">
          <h3>Not computed yet</h3>
          <div className="chips">
            {data.unavailable.map((key) => (
              <span className="chip plain" key={key}>
                {LABELS[key] || key}
              </span>
            ))}
          </div>
          <p className="muted">
            Shown as blank rather than zero on purpose — a zero would read as a
            fact rather than a gap.
          </p>
        </div>
      )}

      <div className="actions">
        <button onClick={load}>Refresh</button>
      </div>
    </>
  );
}

function Banner({ message, onRetry }) {
  return (
    <>
      <header className="bar">
        <h1>Today</h1>
      </header>
      <div className="banner error">{message}</div>
      <div className="actions">
        <button onClick={onRetry}>Try again</button>
      </div>
    </>
  );
}
