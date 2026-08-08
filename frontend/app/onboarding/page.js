"use client";

import { useState } from "react";

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

// Run by whoever is setting a business up, not by the owner. The admin token
// is held in component state and never written to local storage: it mints
// tenants, so it must not outlive the tab it was typed into.
export default function OnboardingPage() {
  const [admin, setAdmin] = useState("");
  const [form, setForm] = useState({
    business_name: "",
    owner_phone: "",
    owner_name: "",
    city: "",
  });
  const [created, setCreated] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${BASE}/api/tenants`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Admin-Token": admin },
        body: JSON.stringify({
          business_name: form.business_name,
          owner_phone: form.owner_phone,
          owner_name: form.owner_name || null,
          city: form.city || null,
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || `Failed (${res.status})`);
      setCreated(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // The token is shown exactly once. It is not stored anywhere in this app and
  // the API does not return it again, so leaving this screen without copying
  // it means issuing a new one.
  if (created) {
    return (
      <>
        <header className="bar">
          <h1>{created.business_name}</h1>
          <div className="sub">Business created. Hand these to the owner.</div>
        </header>

        <div className="card">
          <h3>Phone number</h3>
          <div className="line">
            <span className="v" style={{ fontSize: 18 }}>{form.owner_phone}</span>
          </div>
        </div>

        <div className="card">
          <h3>Access token</h3>
          <p
            style={{
              fontFamily: "ui-monospace, monospace",
              fontSize: 16,
              wordBreak: "break-all",
              background: "var(--surface-2, #f4f4f4)",
              padding: "12px 14px",
              borderRadius: 8,
              margin: "8px 0 12px",
            }}
          >
            {created.token}
          </p>
          <div className="actions">
            <button
              className="primary"
              style={{ width: "100%" }}
              onClick={() => {
                navigator.clipboard?.writeText(created.token);
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy token"}
            </button>
          </div>
          <div className="banner error" style={{ marginTop: 12 }}>
            This is shown once. It is not stored and cannot be shown again — if
            it is lost, the business needs a new token.
          </div>
          <label
            className="line"
            style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}
          >
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              style={{ width: "auto", margin: 0 }}
            />
            <span>I have saved the token somewhere safe.</span>
          </label>
        </div>

        <div className="actions">
          <button
            disabled={!acknowledged}
            style={{ width: "100%" }}
            onClick={() => {
              setCreated(null);
              setForm({ business_name: "", owner_phone: "", owner_name: "", city: "" });
              setCopied(false);
              setAcknowledged(false);
            }}
          >
            Set up another business
          </button>
        </div>
      </>
    );
  }

  const ready = admin.trim() && form.business_name.trim() && form.owner_phone.trim();

  return (
    <>
      <header className="bar">
        <h1>Set up a business</h1>
        <div className="sub">Creates the tenant and issues its access token</div>
      </header>

      {error && <div className="banner error">{error}</div>}

      <div className="card">
        <label htmlFor="admin">Admin token</label>
        <input
          id="admin"
          value={admin}
          onChange={(e) => setAdmin(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          placeholder="not saved on this device"
        />

        {[
          ["business_name", "Business name", "Ravi Fabrics"],
          ["owner_phone", "Owner phone", "98765 43210"],
          ["owner_name", "Owner name (optional)", ""],
          ["city", "City (optional)", "Surat"],
        ].map(([key, label, placeholder]) => (
          <div key={key}>
            <label htmlFor={key} style={{ marginTop: 14 }}>
              {label}
            </label>
            <input
              id={key}
              value={form[key]}
              placeholder={placeholder}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
              autoComplete="off"
            />
          </div>
        ))}

        <div className="actions">
          <button
            className="primary"
            style={{ width: "100%" }}
            disabled={busy || !ready}
            onClick={create}
          >
            {busy ? "Creating…" : "Create business"}
          </button>
        </div>
      </div>
    </>
  );
}
