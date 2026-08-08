"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import TokenGate from "../../components/TokenGate";
import { api, money, formatNumber } from "../../lib/api";

export default function PartyDetailPage() {
  return (
    <TokenGate>
      <PartyDetail />
    </TokenGate>
  );
}

function PartyDetail() {
  const { id } = useParams();
  const [party, setParty] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      setParty(await api.party(id));
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
        <Link href="/parties" className="back">← Parties</Link>
        <div className="banner error">{error}</div>
      </>
    );
  }
  if (!party) return <div className="empty">Loading…</div>;

  const brief = party.brief || {};
  const behaviour = brief.payment_behaviour || {};
  const band = brief.rate_band || {};
  const quotes = (brief.quotes || {}).latest || [];
  const know = knowLines(brief, behaviour, band);

  return (
    <>
      <Link href="/parties" className="back">← Parties</Link>

      <header className="bar">
        <h1>{party.name}</h1>
        <div className="sub">
          {[party.city, party.phone, party.credit_days ? `${party.credit_days} day terms` : null]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </header>

      <div className="stat-grid">
        <div className={`stat${party.days_overdue > 0 ? " pending" : ""}`}>
          <div className="label">Outstanding</div>
          <div className="value">{money(party.outstanding)}</div>
          <div className="note">
            {party.days_overdue > 0 ? `${party.days_overdue} days overdue` : "within terms"}
          </div>
        </div>
        <div className="stat">
          <div className="label">Orders</div>
          <div className="value">{formatNumber((brief.totals || {}).orders || 0)}</div>
          <div className="note">
            {(brief.totals || {}).days_since_last_order != null
              ? `last ${brief.totals.days_since_last_order}d ago`
              : "none yet"}
          </div>
        </div>
      </div>

      {/* What we know — the party brief, in plain sentences. */}
      {know.length > 0 && (
        <div className="know">
          <h3>What we know</h3>
          <ul>
            {know.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {brief.generated_at && (
            <p className="muted" style={{ marginTop: 8, marginBottom: 0 }}>
              Built from this party&apos;s own confirmed records.
            </p>
          )}
        </div>
      )}

      {/* Rate history — what was quoted, countered and agreed. */}
      {quotes.length > 0 && (
        <div className="card">
          <h3>Rate history</h3>
          {quotes.map((q, i) => (
            <div className="row" key={q.extraction_id || i}>
              <div>
                <div>{q.quality || "—"}</div>
                <div className="muted">{q.when || "—"}</div>
              </div>
              <div className="ra" style={{ gap: 10 }}>
                <span style={{ fontWeight: 650 }}>
                  {q.rate != null ? money(q.rate) : "—"}
                </span>
                {q.status && (
                  <span className={`badge-status ${q.status}`}>{q.status}</span>
                )}
              </div>
            </div>
          ))}
          {band.typical != null && (
            <p className="muted" style={{ marginTop: 8, marginBottom: 0 }}>
              Only agreed rates set the usual price ({money(band.typical)}).
            </p>
          )}
        </div>
      )}

      {party.reminder_link && (
        <div className="actions">
          <a
            className="button-link"
            href={party.reminder_link}
            target="_blank"
            rel="noreferrer"
            style={{ flex: 1 }}
          >
            <button className="primary" style={{ width: "100%" }}>
              Draft a reminder
            </button>
          </a>
        </div>
      )}
      {party.reminder_link && (
        <p className="muted">
          Opens WhatsApp with a draft. You send it from your own number — nothing
          is sent automatically.
        </p>
      )}

      {/* The ledger the numbers above are derived from. */}
      <div className="card">
        <h3>Ledger</h3>
        {party.entries.length === 0 ? (
          <p className="muted">No documents yet.</p>
        ) : (
          party.entries
            .slice()
            .reverse()
            .map((e) => (
              <div className="row" key={e.doc_id}>
                <div>
                  <div>
                    {e.doc_type === "invoice" ? "Invoice" : "Payment"}
                    {e.reference ? ` ${e.reference}` : ""}
                  </div>
                  <div className="muted">{e.date || "—"}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontWeight: 650 }}>
                    {e.debit ? money(e.debit) : `− ${money(e.credit)}`}
                  </div>
                  <div className="muted">bal {money(e.balance)}</div>
                </div>
              </div>
            ))
        )}
      </div>

      {party.orders.length > 0 && (
        <div className="card">
          <h3>Orders</h3>
          {party.orders.map((o) => (
            <Link
              key={o.id}
              href={`/orders/${o.id}`}
              className="row"
              style={{ textDecoration: "none", color: "inherit" }}
            >
              <div>
                <div>{o.order_no || "Order"}</div>
                <div className="muted">
                  {o.order_date || "—"} · {o.lines} line{o.lines === 1 ? "" : "s"}
                </div>
              </div>
              <div className="muted">
                {o.pending_fields?.length ? (
                  <span className="pending-tag">needs {o.pending_fields.length}</span>
                ) : (
                  o.status
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

function knowLines(brief, behaviour, band) {
  const lines = [];
  const buys = (brief.buys || []).slice(0, 3);
  if (buys.length) {
    lines.push(
      `Buys ${buys.map((b) => `${b.quality} (${b.times}×)`).join(", ")}.`
    );
  }
  if (band.typical != null) {
    const spread =
      band.low != null && band.high != null && band.low !== band.high
        ? ` (${money(band.low)}–${money(band.high)})`
        : "";
    lines.push(`Usual rate ${money(band.typical)}${spread}.`);
  }
  if (behaviour.avg_days_to_settle != null) {
    const terms = behaviour.terms_days
      ? ` against ${behaviour.terms_days} day terms`
      : "";
    lines.push(
      `Settles in about ${Math.round(behaviour.avg_days_to_settle)} days${terms}.`
    );
  }
  if (behaviour.modes?.length) {
    lines.push(`Usually pays by ${behaviour.modes[0].mode.toUpperCase()}.`);
  }
  if (behaviour.unapplied_credit > 0) {
    lines.push(`${money(behaviour.unapplied_credit)} paid but not yet matched to a bill.`);
  }
  const totals = brief.totals || {};
  if (totals.days_since_contact != null) {
    lines.push(
      totals.days_since_contact === 0
        ? "In touch today."
        : `Last in touch ${totals.days_since_contact} days ago.`
    );
  }
  const complaints = brief.complaints || {};
  if (complaints.count) {
    const last = (complaints.recent || [])[0];
    lines.push(
      `${complaints.count} complaint${complaints.count === 1 ? "" : "s"} on record` +
        (last?.what ? ` — most recently: ${last.what}` : ".")
    );
  } else {
    lines.push("No complaint history.");
  }
  return lines;
}
