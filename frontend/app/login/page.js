"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, setToken, setPhone, clearToken, samePhone } from "../lib/api";

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
      router.replace(params.get("next") || "/");
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
    <>
      <header className="bar">
        <h1>Textile Ops</h1>
        <div className="sub">Sign in to your business</div>
      </header>

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
      </div>
    </>
  );
}
