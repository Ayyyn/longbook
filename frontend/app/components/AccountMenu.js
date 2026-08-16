"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, getToken, clearToken } from "../lib/api";

// The conventional pattern, because this is the one control people already
// know how to find: initial top right, menu beneath, click outside or Escape
// to close. Present on every screen, signed in or not — a signed-out visitor
// needs a way in from wherever they landed.
export default function AccountMenu() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [me, setMe] = useState(null);
  const [signedIn, setSignedIn] = useState(false);
  const wrap = useRef(null);

  const load = useCallback(async () => {
    if (!getToken()) {
      setSignedIn(false);
      setMe(null);
      return;
    }
    setSignedIn(true);
    // A failure here is not worth a visible error: the menu degrades to
    // showing just the actions.
    setMe(await api.me().catch(() => null));
  }, []);

  // Re-read on navigation so signing in or out is reflected without a reload.
  useEffect(() => {
    load();
    setOpen(false);
    // Signing in mid-flow does not navigate, so the menu has to be told.
    window.addEventListener("auth-changed", load);
    return () => window.removeEventListener("auth-changed", load);
  }, [load, pathname]);

  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => {
      if (wrap.current && !wrap.current.contains(e.target)) setOpen(false);
    };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const initial = (me?.business_name || "?").trim().charAt(0).toUpperCase();

  return (
    <div className="account" ref={wrap}>
      <button
        className="account-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={signedIn ? "Account" : "Sign in"}
        onClick={() => setOpen((v) => !v)}
      >
        {signedIn ? initial : "?"}
      </button>

      {open && (
        <div className="account-menu" role="menu">
          {signedIn ? (
            <>
              <div className="account-head">
                <div className="who">{me?.business_name || "Your business"}</div>
                {me?.owner_name && <div className="line">{me.owner_name}</div>}
                {me?.owner_phone && <div className="line">{me.owner_phone}</div>}
                {me?.owner_email && <div className="line">{me.owner_email}</div>}
              </div>

              {me?.access_status && (
                <div className="account-plan">
                  <span className={`badge-status ${me.access_status}`}>
                    {me.access_status === "trial" ? "Trial" : me.plan || "Active"}
                  </span>
                  {me.days_remaining != null && (
                    <span className="muted">
                      {me.days_remaining} {me.days_remaining === 1 ? "day" : "days"} left
                    </span>
                  )}
                </div>
              )}

              <Link href="/add" role="menuitem" onClick={() => setOpen(false)}>
                Add data
              </Link>
              <Link href="/chat" role="menuitem" onClick={() => setOpen(false)}>
                Ask a question
              </Link>
              {/* Below "Ask a question" rather than in the bottom bar: both are
                  read occasionally, and the bar is for the five screens used
                  every day. */}
              <Link href="/business" role="menuitem" onClick={() => setOpen(false)}>
                About the business
              </Link>
              <Link href="/activity" role="menuitem" onClick={() => setOpen(false)}>
                Activity
              </Link>
              <div className="account-sep" />
              <Link href="/privacy" role="menuitem" onClick={() => setOpen(false)}>
                Privacy
              </Link>
              <Link href="/terms" role="menuitem" onClick={() => setOpen(false)}>
                Terms
              </Link>
              <div className="account-sep" />
              <button
                role="menuitem"
                className="danger-item"
                onClick={() => {
                  clearToken();
                  window.location.replace("/login");
                }}
              >
                Sign out
              </button>
            </>
          ) : (
            <>
              <div className="account-head">
                <div className="who">Not signed in</div>
              </div>
              <Link href="/login" role="menuitem" onClick={() => setOpen(false)}>
                Sign in
              </Link>
              <Link href="/signup" role="menuitem" onClick={() => setOpen(false)}>
                Set up my business
              </Link>
              <div className="account-sep" />
              <Link href="/privacy" role="menuitem" onClick={() => setOpen(false)}>
                Privacy
              </Link>
              <Link href="/terms" role="menuitem" onClick={() => setOpen(false)}>
                Terms
              </Link>
            </>
          )}
        </div>
      )}
    </div>
  );
}
