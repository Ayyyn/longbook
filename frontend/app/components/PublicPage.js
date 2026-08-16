"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getToken } from "../lib/api";

// Chrome for the pages a stranger sees. Read on a phone, in daylight, by
// someone in their fifties who has been doing this trade for thirty years —
// so: big type, hard contrast, no gradients, and nothing that has to be
// scrolled past to reach the point.
export default function PublicPage({ children, active }) {
  // Signup hands the owner a token at step one, so from step two onward
  // the nav saying "Sign in" is simply wrong — and tapping it mid-setup
  // is how someone loses their place.
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    const read = () => setSignedIn(Boolean(getToken()));
    read();
    window.addEventListener("auth-changed", read);
    window.addEventListener("storage", read);
    return () => {
      window.removeEventListener("auth-changed", read);
      window.removeEventListener("storage", read);
    };
  }, []);

  const links = [
    ["/", "Home"],
    ["/pricing", "Pricing"],
    ["/contact", "Contact"],
  ];

  return (
    <div className="public">
      <nav className="public-nav">
        <Link href="/" className="wordmark">
          Longbook
        </Link>
        {/* Home is listed explicitly as well as being the wordmark. The
            wordmark is only obvious as a home link to people who already know
            that convention, and this audience largely does not. */}
        <div className="public-links">
          {links.map(([href, label]) => (
            <Link key={href} href={href} className={active === href ? "on" : ""}>
              {label}
            </Link>
          ))}
          <Link href={signedIn ? "/today" : "/login"} className="on">
            {signedIn ? "My dashboard" : "Sign in"}
          </Link>
        </div>
      </nav>

      {children}

      {/* Links only. The address lives on the contact page and in the calls to
          action, where someone is actually deciding to get in touch. */}
      <footer className="public-footer">
        <div className="rows small">
          {[...links, ["/privacy", "Privacy"], ["/terms", "Terms"]].map(
            ([href, label]) => (
              <Link key={href} href={href}>
                {label}
              </Link>
            ),
          )}
        </div>
      </footer>
    </div>
  );
}
