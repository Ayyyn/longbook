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
      <NewHere />
    </PublicPage>
  );
}

// The invite code is the one field an owner cannot fix themselves, so it is
// asked first and checked on its own. Being told the code is wrong *after*
// typing a business name, a phone number and an email is a small insult that
// loses people at the door.
//
// The email is taken here too because it is where the access token is sent,
// and a token nobody received is the single most expensive thing that can go
// wrong in this flow. Both are handed to /signup so nothing is asked twice.
function NewHere() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function check() {
    setBusy(true);
    setError(null);
    try {
      await api.checkInvite(code.trim());
      // sessionStorage, not the URL: a code in a query string ends up in
      // history, in screenshots and in anything the browser syncs.
      sessionStorage.setItem("lb-invite", code.trim());
      sessionStorage.setItem("lb-email", email.trim());
      router.push("/signup");
    } catch (err) {
      setError(
        err.status === 401
          ? "That code is not right. Check it against the message we sent you."
          : err.message,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="empty-state">
      <h3>New here?</h3>
      <div className="why">
        Longbook keeps track of your orders, payments, customers and
        commitments, using the records your business already produces. Nothing
        is typed in twice and nothing changes for your customers.
      </div>

      {!open ? (
        <>
          <button className="primary" onClick={() => setOpen(true)}>
            Set up my business
          </button>
          <p className="muted" style={{ marginBottom: 0 }}>
            You will need an invite code. Email{" "}
            <a href={CONTACT.emailHref}>{CONTACT.email}</a> and we will tell you
            whether it suits your business.
          </p>
        </>
      ) : (
        <div style={{ textAlign: "left", marginTop: 8 }}>
          {error && <div className="banner error">{error}</div>}

          <label htmlFor="invite">Invite code</label>
          <input
            id="invite"
            value={code}
            autoFocus
            placeholder="the code you were given"
            onChange={(e) => setCode(e.target.value)}
          />

          <label htmlFor="invite-email" style={{ marginTop: 12 }}>
            Your email
          </label>
          <input
            id="invite-email"
            type="email"
            value={email}
            placeholder="you@business.in"
            onChange={(e) => setEmail(e.target.value)}
          />
          <p className="muted">
            Your access token is emailed here the moment your business is
            created. It is the only copy you get, so use an address you can
            search later.
          </p>

          <div className="actions">
            <button disabled={busy} onClick={() => setOpen(false)}>
              Back
            </button>
            <button
              className="primary"
              disabled={busy || !code.trim() || !email.trim()}
              onClick={check}
            >
              {busy ? "Checking…" : "Continue"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
