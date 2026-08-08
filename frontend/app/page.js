"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import TokenGate from "./components/TokenGate";
import { api, money, formatNumber } from "./lib/api";

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

  if (error) {
    return (
      <>
        <header className="bar">
          <h1>Today</h1>
        </header>
        <div className="banner error">{error}</div>
        <div className="actions">
          <button onClick={load}>Try again</button>
        </div>
      </>
    );
  }
  if (!data) return <div className="empty">Loading…</div>;

  const when = new Date(data.date).toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "short",
  });

  return (
    <>
      <header className="bar">
        <h1>Today</h1>
        <div className="sub">
          {when} · {me?.business_name}
        </div>
      </header>

      {/* Money in is the one number an owner opens the app for. */}
      <div className="hero">
        <div className="label">Received today</div>
        <div className="value">{money(data.money_in.today)}</div>
        <div className="note">
          {data.money_in.payments_today} payment
          {data.money_in.payments_today === 1 ? "" : "s"}
          {data.money_in.last_7_days > data.money_in.today
            ? ` · ${money(data.money_in.last_7_days)} this week`
            : ""}
        </div>
      </div>

      <Section title="Needs chasing" count={data.overdue.parties}>
        {data.chasing.length === 0 ? (
          <p className="section-empty">Nobody past {data.overdue.overdue_days} days.</p>
        ) : (
          data.chasing.map((p) => (
            <Link key={p.party_id} href={`/parties/${p.party_id}`} className="section-row">
              <div>
                <div className="rt">{p.party_name}</div>
                <div className="rs warn">{p.days_overdue} days past due</div>
              </div>
              <div className="ra">
                {money(p.outstanding)} <span className="chev">›</span>
              </div>
            </Link>
          ))
        )}
      </Section>

      {data.flagged.length > 0 && (
        <Section title="Flagged">
          {data.flagged.map((f, i) => {
            const href = f.order_id
              ? `/orders/${f.order_id}`
              : f.party_id
                ? `/parties/${f.party_id}`
                : null;
            const body = (
              <>
                <div className="rt">{f.headline}</div>
                <div className="rs">{f.party_name}</div>
              </>
            );
            return href ? (
              <Link key={i} href={href} className="section-row">
                <div>{body}</div>
                <div className="ra"><span className="chev">›</span></div>
              </Link>
            ) : (
              <div key={i} className="section-row">
                <div>{body}</div>
              </div>
            );
          })}
        </Section>
      )}

      <Section title="New orders" count={data.orders.open_total}>
        {data.new_orders.length === 0 ? (
          <p className="section-empty">Nothing open.</p>
        ) : (
          data.new_orders.map((o) => (
            <Link key={o.id} href={`/orders/${o.id}`} className="section-row">
              <div>
                <div className="rt">{o.party_name || "Unknown party"}</div>
                <div className="rs">{o.summary}</div>
              </div>
              <div className="ra">
                {o.pending_fields.length > 0 && (
                  <span className="pending-tag">needs {o.pending_fields.length}</span>
                )}
                <span className="chev">›</span>
              </div>
            </Link>
          ))
        )}
      </Section>

      {data.needs_review > 0 && (
        <Link href="/review" className="section-row cta">
          <div>
            <div className="rt">{formatNumber(data.needs_review)} waiting in Review</div>
            <div className="rs">confirm what the agents were unsure about</div>
          </div>
          <div className="ra"><span className="chev">›</span></div>
        </Link>
      )}

      {/* Running low needs the stock maths. Named rather than left out: an
          absent section would read as "nothing is running low". */}
      <Section title="Running low">
        <p className="section-empty">Not computed yet — stock tracking is not built.</p>
      </Section>

      <div className="actions">
        <button onClick={load}>Refresh</button>
      </div>
    </>
  );
}

function Section({ title, count, children }) {
  return (
    <section className="feed">
      <h2>
        {title}
        {count ? <span className="count">{count}</span> : null}
      </h2>
      {children}
    </section>
  );
}
