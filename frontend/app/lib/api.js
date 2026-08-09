"use client";

// One place that knows about the API and the token. The token is the tenant —
// see app/api/deps.py — so everything goes through here.

const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const TOKEN_KEY = "textile-ops-token";
const PHONE_KEY = "textile-ops-phone";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  window.localStorage.setItem(TOKEN_KEY, token.trim());
}

export function getPhone() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(PHONE_KEY);
}

export function setPhone(phone) {
  window.localStorage.setItem(PHONE_KEY, (phone || "").trim());
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(PHONE_KEY);
}

// Phones get typed with spaces, dashes and a country code that comes and goes.
// Compare on digits, and on the last ten of them — +91 98765 43210, 09876543210
// and 9876543210 are one number.
export function samePhone(a, b) {
  const digits = (v) => (v || "").replace(/\D/g, "").slice(-10);
  const left = digits(a);
  return left.length === 10 && left === digits(b);
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

  if (res.status === 401) {
    // The stored token is dead — a rotated token, or a database that was
    // rebuilt under it. Drop it and send them to sign-in rather than leaving
    // every screen showing the same red banner forever.
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      // Remember where they were so signing back in resumes the tap that
      // failed, instead of dumping them on Today.
      const next = window.location.pathname + window.location.search;
      window.location.replace(`/login?next=${encodeURIComponent(next)}`);
    }
  }

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
  // null when this tenant has never uploaded anything.
  latestJob: () => request("/api/ingest/jobs/latest"),
  resumeBackfill: () => request("/api/ingest/resume", { method: "POST" }),
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

  parties: (options = {}) => {
    const query = new URLSearchParams();
    if (options.q) query.set("q", options.q);
    if (options.overdueOnly) query.set("overdue_only", "true");
    if (options.hasOutstanding) query.set("has_outstanding", "true");
    return request(`/api/parties?${query}`);
  },
  party: (id) => request(`/api/parties/${id}`),

  orders: (options = {}) => {
    const query = new URLSearchParams({ limit: "100" });
    if (options.status) query.set("status", options.status);
    if (options.partyId) query.set("party_id", options.partyId);
    return request(`/api/orders?${query}`);
  },
  order: (id) => request(`/api/orders/${id}`),

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
