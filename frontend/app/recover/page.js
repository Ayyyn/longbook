"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import PublicPage from "../components/PublicPage";
import { requestRecovery, confirmRecovery, setToken, setPhone } from "../lib/api";
import { CONTACT } from "../lib/contact";

export default function RecoverPage() {
  return (
    <Suspense fallback={<div className="empty">Loading…</div>}>
      <Recover />
    </Suspense>
  );
}

function Recover() {
  const params = useSearchParams();
  const signed = params.get("t");

  // One route, two jobs: asking for the link, and opening it. Keeping them on
  // the same path means the email points at something the owner recognises.
  return signed ? <Confirm signed={signed} /> : <Ask />;
}

function Ask() {
  const [phone, setPhoneValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await requestRecovery(phone);
      setSent(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <PublicPage>
        <section className="hero-public">
          <h1>Check your email</h1>
        </section>
        <div className="empty-state">
          <div className="why">
            If that number belongs to a business with an email on file, we have
            sent a link to it. The link works for 30 minutes.
            <br />
            <br />
            Opening it gives you a new token and stops your old one working, so
            only open it if you actually need it.
          </div>
        </div>
        <p className="muted" style={{ textAlign: "center" }}>
          No email? Ring <a href={CONTACT.phoneHref}>{CONTACT.phone}</a> and we
          will sort it out.
        </p>
      </PublicPage>
    );
  }

  return (
    <PublicPage>
      <section className="hero-public">
        <h1>Lost your token?</h1>
        <p className="lede">
          Give us the phone number your business is registered with and we will
          email a link for a new one.
        </p>
      </section>

      {error && <div className="banner error">{error}</div>}

      <div className="card">
        <label htmlFor="phone">Phone number</label>
        <input
          id="phone"
          value={phone}
          onChange={(e) => setPhoneValue(e.target.value)}
          placeholder="98765 43210"
          type="tel"
          inputMode="numeric"
          autoComplete="tel"
        />
        <div className="actions">
          <button
            className="primary"
            style={{ width: "100%" }}
            disabled={busy || phone.replace(/\D/g, "").length < 10}
            onClick={submit}
          >
            {busy ? "Sending…" : "Email me a link"}
          </button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          The link goes to the email address on your account. We cannot look up
          your old token — it is not stored anywhere we can read.
        </p>
      </div>

      <p className="muted" style={{ textAlign: "center" }}>
        <Link href="/login">Back to sign in</Link>
      </p>
    </PublicPage>
  );
}

function Confirm({ signed }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    confirmRecovery(signed)
      .then((body) => {
        if (cancelled) return;
        // Sign them in here and now. Making someone paste a token they are
        // holding on the same screen is a step with no purpose.
        setToken(body.token);
        if (body.owner_phone) setPhone(body.owner_phone);
        setResult(body);
      })
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [signed]);

  if (error) {
    return (
      <PublicPage>
        <section className="hero-public">
          <h1>That link did not work</h1>
        </section>
        <div className="banner error">{error}</div>
        <p className="muted">
          Links last 30 minutes and work once. Ask for another, or ring{" "}
          <a href={CONTACT.phoneHref}>{CONTACT.phone}</a>.
        </p>
        <div className="actions">
          <Link href="/recover" className="button-link" style={{ flex: 1 }}>
            <button className="primary" style={{ width: "100%" }}>
              Send me another link
            </button>
          </Link>
        </div>
      </PublicPage>
    );
  }

  if (!result) {
    return (
      <PublicPage>
        <div className="empty">Issuing your new token…</div>
      </PublicPage>
    );
  }

  return (
    <PublicPage>
      <section className="hero-public">
        <h1>{result.business_name}</h1>
        <p className="lede">You are signed in on this device again.</p>
      </section>

      <div className="card">
        <h3>Your new access token</h3>
        <p
          style={{
            fontFamily: "ui-monospace, monospace",
            fontSize: 16,
            wordBreak: "break-all",
            background: "var(--card-2)",
            padding: "12px 14px",
            borderRadius: 10,
            margin: "8px 0 12px",
          }}
        >
          {result.token}
        </p>
        <div className="actions">
          <button
            className="primary"
            style={{ width: "100%" }}
            onClick={() => {
              navigator.clipboard?.writeText(result.token);
              setCopied(true);
            }}
          >
            {copied ? "Copied" : "Copy token"}
          </button>
        </div>
        {result.emailed_to ? (
          <div className="banner" style={{ marginTop: 12 }}>
            We have emailed it to <strong>{result.emailed_to}</strong> as well.
          </div>
        ) : (
          <div className="banner error" style={{ marginTop: 12 }}>
            Save this now — it is shown once.
          </div>
        )}
        <p className="muted" style={{ marginBottom: 0 }}>
          Your previous token has stopped working. Any other phone signed in
          with it will need this one.
        </p>
      </div>

      <div className="actions">
        <Link href="/today" className="button-link" style={{ flex: 1 }}>
          <button className="primary big">Open my dashboard</button>
        </Link>
      </div>
    </PublicPage>
  );
}
