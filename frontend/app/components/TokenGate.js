"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, getToken, clearToken } from "../lib/api";
import { CONTACT } from "../lib/contact";

// Guards every signed-in screen, and answers two questions before any of them
// renders: is there a token, and is this business still allowed in.
//
// The access check lives here rather than in each screen because the API
// answers 402 on every one of them — without a single place to catch it the
// owner would get seven different broken screens instead of one clear message.
export default function TokenGate({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState("checking"); // checking|ok|expired
  const [me, setMe] = useState(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(pathname || "/today")}`);
      return;
    }
    // /api/tenants/me is deliberately not access-guarded, so an expired owner
    // can still be told why they are locked out and who to call.
    api
      .me()
      .then((profile) => {
        setMe(profile);
        setState(profile.access_status === "expired" ? "expired" : "ok");
      })
      // A failure here is not an access decision — let the screen itself
      // report whatever went wrong rather than claiming the account expired.
      .catch(() => setState("ok"));
  }, [router, pathname]);

  if (state === "checking") return null;
  if (state === "expired") return <Expired me={me} />;

  return (
    <>
      {children}
      {/* Only near the end. A 14-day window on a 14-day trial means it
          shows from the first minute, which reads as nagging. */}
      {me?.days_remaining != null && me.days_remaining <= 5 && (
        <Countdown days={me.days_remaining} status={me.access_status} />
      )}
    </>
  );
}

// Deliberately quiet, and only in the last few days. An owner who has paid
// should not be reminded of it every morning.
function Countdown({ days, status }) {
  return (
    <p className="muted" style={{ textAlign: "center", marginTop: 14 }}>
      {status === "trial" ? "Trial ends" : "Your subscription ends"} in {days}{" "}
      {days === 1 ? "day" : "days"}.{" "}
      <a href={CONTACT.phoneHref}>Call {CONTACT.phone}</a> to renew.
    </p>
  );
}

function Expired({ me }) {
  return (
    <>
      <header className="bar">
        <h1>{me?.business_name || "Textile Ops"}</h1>
        <div className="sub">Access has ended</div>
      </header>

      <div className="empty-state">
        <h3>Your access has ended</h3>
        <div className="why">
          {me?.access_status === "expired" && me?.paid_until
            ? "Your subscription ran out. "
            : "Your trial has finished. "}
          <strong>Nothing has been deleted.</strong> Every order, payment and
          party is exactly where you left it, and comes back the moment your
          access is renewed.
        </div>
      </div>

      <div className="card">
        <h3>To renew</h3>
        <div className="row">
          <div className="muted">Phone</div>
          <div style={{ fontWeight: 600 }}>
            <a href={CONTACT.phoneHref}>{CONTACT.phone}</a>
          </div>
        </div>
        <div className="row">
          <div className="muted">WhatsApp</div>
          <div style={{ fontWeight: 600 }}>
            <a href={CONTACT.whatsappHref} target="_blank" rel="noreferrer">
              Message us
            </a>
          </div>
        </div>
        <div className="row">
          <div className="muted">Email</div>
          <div style={{ fontWeight: 600 }}>
            <a href={CONTACT.emailHref}>{CONTACT.email}</a>
          </div>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          {CONTACT.hours}. Payment is taken in person or by transfer — there is
          nothing to pay for inside the app.
        </p>
      </div>

      <p className="muted" style={{ textAlign: "center", marginTop: 16 }}>
        <button
          className="link-button"
          onClick={() => {
            clearToken();
            window.location.replace("/login");
          }}
        >
          Sign out
        </button>
      </p>
    </>
  );
}
