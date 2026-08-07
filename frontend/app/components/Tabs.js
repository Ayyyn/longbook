"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Today" },
  { href: "/review", label: "Review" },
  { href: "/parties", label: "Parties" },
  { href: "/orders", label: "Orders" },
  { href: "/activity", label: "Activity" },
];

export default function Tabs() {
  const pathname = usePathname();
  return (
    <nav className="tabs">
      {TABS.map((tab) => {
        // A detail page belongs to its section, so /parties/<id> keeps the
        // Parties tab lit rather than leaving the owner with no idea where
        // they are.
        const active =
          tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
        return (
          <Link key={tab.href} href={tab.href} className={active ? "active" : ""}>
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
