"use client";

import Link from "next/link";
import { CONTACT } from "../lib/contact";

// Chrome for the pages a stranger sees. Read on a phone, in daylight, by
// someone in their fifties who has been doing this trade for thirty years —
// so: big type, hard contrast, no gradients, and nothing that has to be
// scrolled past to reach the point.
export default function PublicPage({ children, active }) {
  const links = [
    ["/", "Home"],
    ["/pricing", "Pricing"],
    ["/about", "About"],
    ["/contact", "Contact"],
  ];

  return (
    <div className="public">
      <nav className="public-nav">
        <Link href="/" className="wordmark">
          Textile Ops
        </Link>
        <div className="public-links">
          {links.slice(1).map(([href, label]) => (
            <Link key={href} href={href} className={active === href ? "on" : ""}>
              {label}
            </Link>
          ))}
          <Link href="/login" className="on">
            Sign in
          </Link>
        </div>
      </nav>

      {children}

      <footer className="public-footer">
        <div className="rows">
          <a href={CONTACT.phoneHref}>{CONTACT.phone}</a>
          <a href={CONTACT.emailHref}>{CONTACT.email}</a>
        </div>
        <p>
          Made in Surat. We do not send anything to your customers, ever.
        </p>
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
