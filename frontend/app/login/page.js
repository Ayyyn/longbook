"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, setToken, setPhone, clearToken, samePhone } from "../lib/api";
import PublicPage from "../components/PublicPage";
import { CONTACT } from "../lib/contact";

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="empty">Loading…</div>}>
      <Login />
    </Suspense>
  );
}

function Login() {
  const router = useRouter();
  const params = useSearchParams();
  const [phone, setPhoneValue] = useState("");
  const [token, setTokenValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // The token alone is what the API authenticates — the phone is checked
  // against the tenant it belongs to, so pasting someone else's token into
  // your own phone number fails here rather than silently opening their books.
  async function signIn() {
    setBusy(true);
    setError(null);
    setToken(token);
    try {
      const me = await api.me();
      if (!samePhone(phone, me.owner_phone)) {
        clearToken();
        setError("That token belongs to a different phone number.");
        return;
      }
      setPhone(phone);
      router.replace(params.get("next") || "/today");
    } catch (err) {
      clearToken();
      setError(
        err.status === 401
          ? "That token was not recognised. Check it and try again."
          : err.message,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicPage>
      <section className="hero-public">
        <h1>Sign in</h1>
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

        <label htmlFor="token" style={{ marginTop: 14 }}>
          Access token
        </label>
        <input
          id="token"
          value={token}
          onChange={(e) => setTokenValue(e.target.value)}
          placeholder="tex_…"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
        />

        <div className="actions">
          <button
            className="primary"
            style={{ width: "100%" }}
            disabled={busy || !phone.trim() || !token.trim()}
            onClick={signIn}
          >
            {busy ? "Checking…" : "Sign in"}
          </button>
        </div>

        <p className="muted">
          Both were given to you when your business was set up. They stay on
          this phone — nothing is sent anywhere else.
        </p>
        <p className="muted" style={{ marginBottom: 0 }}>
          <Link href="/recover">Lost your token?</Link>
        </p>
      </div>

      {/* Without this, someone who has never been set up lands on a form
          demanding a token they have no way to get, and there the journey
          ends. */}
      <div className="empty-state">
        <h3>New here?</h3>
        <div className="why">
          Longbook reads your WhatsApp chats and keeps the orders, payments
          and outstandings for you — no typing, no new app for your customers.
        </div>
        <Link href="/signup" className="button-link">
          <button className="primary">Set up my business</button>
        </Link>
        <p className="muted" style={{ marginBottom: 0 }}>
          You will need an invite code. Ring{" "}
          <a href={CONTACT.emailHref}>{CONTACT.email}</a> and we will tell you
          whether it suits your business.
        </p>
      </div>
    </PublicPage>
  );
}
