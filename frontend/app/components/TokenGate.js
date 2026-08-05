"use client";

import { useEffect, useState } from "react";
import { getToken, setToken, clearToken } from "../lib/api";

// Stands in for owner sign-in. The token is issued at onboarding and pasted in
// once; Firebase OTP replaces this whole component later.
export default function TokenGate({ children }) {
  const [ready, setReady] = useState(false);
  const [hasToken, setHasToken] = useState(false);
  const [value, setValue] = useState("");

  useEffect(() => {
    setHasToken(Boolean(getToken()));
    setReady(true);
  }, []);

  if (!ready) return null; // avoids a flash of the sign-in card on every load

  if (!hasToken) {
    return (
      <>
        <header className="bar">
          <h1>Textile Ops</h1>
          <div className="sub">Sign in with your business token</div>
        </header>
        <div className="card">
          <label htmlFor="token">Token</label>
          <input
            id="token"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="tex_..."
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
          />
          <div className="actions">
            <button
              className="primary"
              disabled={!value.trim()}
              onClick={() => {
                setToken(value);
                setHasToken(true);
              }}
            >
              Continue
            </button>
          </div>
          <p className="muted">
            Given to you when your business was set up. It stays on this phone.
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      {children}
      <div className="actions">
        <button
          onClick={() => {
            clearToken();
            setHasToken(false);
            setValue("");
          }}
        >
          Sign out
        </button>
      </div>
    </>
  );
}
