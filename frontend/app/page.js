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

        <div className="stat">
          <div className="label">New orders</div>
          <div className="value">{formatNumber(data.orders.new_today)}</div>
          <div className="note">{data.orders.new_last_7_days} this week</div>
        </div>

        <div className="stat">
          <div className="label">Open orders</div>
          <div className="value">{formatNumber(data.orders.open_total)}</div>
          <div className="note">{data.orders.awaiting_confirmation} to confirm</div>
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

      <div className="card">
        <strong>Recent payments</strong>
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
              <div style={{ fontWeight: 650 }}>{money(payment.amount)}</div>
            </div>
          ))
        )}
      </div>

      {data.unavailable.length > 0 && (
        <div className="card">
          <strong>Not computed yet</strong>
          <div className="chips">
            {data.unavailable.map((key) => (
              <span className="chip plain" key={key}>
                {LABELS[key] || key}
              </span>
            ))}
          </div>
          <p className="muted">
            These need the ledger. Shown as blank rather than zero on purpose — a
            zero here would read as &ldquo;nobody owes you anything&rdquo;.
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
