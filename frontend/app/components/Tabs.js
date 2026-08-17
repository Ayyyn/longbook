"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "../lib/api";

// Five, in the order they get used. Review sits last because it is a chore
// rather than a destination — an owner opens the app to see today, not to be
// asked questions. Business and Activity moved into the account menu: they
// are read once a month, and a bottom bar on a phone has room for what is
// read daily and nothing more.
const TABS = [
  { href: "/today", label: "Today" },
  { href: "/parties", label: "Parties" },
  { href: "/orders", label: "Orders" },
  { href: "/notes", label: "Notes" },
  { href: "/review", label: "Review" },
];

// Screens you reach without being signed in. The tab bar would be five dead
// links there, and on a phone it would cover the sign-in button.
// Public pages and the ways in. The tab bar is for signed-in screens only.
const CHROMELESS = ["/login", "/signup", "/recover", "/onboarding", "/privacy", "/terms", "/pricing", "/contact"];
const PUBLIC_HOME = "/";

export default function Tabs() {
  const pathname = usePathname();
  // The count on Review. An owner should not have to open a tab to find out
  // whether it wants anything from them.
  const [waiting, setWaiting] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.today()
      .then((d) => {
        if (!cancelled) setWaiting(d?.needs_review || 0);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // Re-read on navigation: confirming an item should drop the badge without
    // a reload.
  }, [pathname]);

  if (pathname === PUBLIC_HOME) return null;
  if (CHROMELESS.some((p) => pathname.startsWith(p))) return null;
  return (
    <nav className="tabs">
      {/* Desktop only: the rail is tall enough to carry the name, and
          without it the app opens with no identity at all. CSS hides it
          on phones, where the bottom bar has no room to spare. */}
      <Link href="/" className="rail-mark">
        Longbook
      </Link>
      {TABS.map((tab) => {
        // A detail page belongs to its section, so /parties/<id> keeps the
        // Parties tab lit rather than leaving the owner with no idea where
        // they are.
        const active =
          pathname === tab.href || pathname.startsWith(`${tab.href}/`);
        const badge = tab.href === "/review" && waiting > 0 ? waiting : null;
        return (
          <Link key={tab.href} href={tab.href} className={active ? "active" : ""}>
            <span className="tab-label">
              {tab.label}
              {badge != null && (
                <sup className="tab-badge" aria-label={`${badge} waiting`}>
                  {badge > 99 ? "99+" : badge}
                </sup>
              )}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
