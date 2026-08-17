"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Five, in the order they get used. Analytics takes the last slot from
// Review, which has moved to the account menu: Review is a chore rather than a
// destination — it is opened because the app asked, and the badge in the
// account menu still says when it has. Analytics is somewhere an owner goes on
// purpose, which is what a bottom-bar slot is for.
//
// Business and Activity live in the account menu for the same reason: read
// once a month, and a phone's bottom bar has room for what is read daily.
const TABS = [
  { href: "/today", label: "Today" },
  { href: "/parties", label: "Parties" },
  { href: "/orders", label: "Orders" },
  { href: "/notes", label: "Notes" },
  { href: "/analytics", label: "Analytics" },
];

// Screens you reach without being signed in. The tab bar would be five dead
// links there, and on a phone it would cover the sign-in button.
// Public pages and the ways in. The tab bar is for signed-in screens only.
const CHROMELESS = ["/login", "/signup", "/recover", "/onboarding", "/privacy", "/terms", "/pricing", "/contact"];
const PUBLIC_HOME = "/";

export default function Tabs() {
  const pathname = usePathname();
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
        return (
          <Link key={tab.href} href={tab.href} className={active ? "active" : ""}>
            <span className="tab-label">{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
