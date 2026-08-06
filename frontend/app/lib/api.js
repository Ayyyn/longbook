"use client";

// One place that knows about the API and the token. The token is the tenant —
// see app/api/deps.py — so everything goes through here.

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const TOKEN_KEY = "textile-ops-token";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  window.localStorage.setItem(TOKEN_KEY, token.trim());
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      // Non-JSON error body; the status is all we have.
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  today: () => request("/api/today"),
  me: () => request("/api/tenants/me"),
  queue: (limit = 25) => request(`/api/review/queue?limit=${limit}`),
  accept: (id) => request(`/api/review/${id}/accept`, { method: "POST" }),
  correct: (id, payload) =>
    request(`/api/review/${id}/correct`, { method: "POST", body: JSON.stringify(payload) }),
  reject: (id, reason) =>
    request(`/api/review/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: reason || null }),
    }),

  agentSummary: (days = 30) => request(`/api/agents/summary?days=${days}`),
  agentRuns: (options = {}) => {
    const query = new URLSearchParams({ limit: "30" });
    if (options.overrides_only) query.set("overrides_only", "true");
    if (options.outcome) query.set("outcome", options.outcome);
    if (options.agent) query.set("agent", options.agent);
    return request(`/api/agents/runs?${query}`);
  },
  agentTrace: (traceId) => request(`/api/agents/trace/${traceId}`),
};

// ₹1,25,000 — lakh grouping, not thousands. Getting this wrong is the fastest
// way to look foreign to the person reading it.
const RUPEES = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export function money(value) {
  return RUPEES.format(Number(value || 0));
}

export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isNaN(n) ? String(value) : new Intl.NumberFormat("en-IN").format(n);
}
