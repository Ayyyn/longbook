"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Two screens for now. Parties, Orders and Agent Activity join them in
// BUILD_PROMPT section 5.
const TABS = [
  { href: "/", label: "Today" },
  { href: "/review", label: "Review" },
];

export default function Tabs() {
  const pathname = usePathname();
  return (
    <nav className="tabs">
      {TABS.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          className={pathname === tab.href ? "active" : ""}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
