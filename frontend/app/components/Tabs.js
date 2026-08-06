"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Parties and Orders join these in BUILD_PROMPT section 5.
const TABS = [
  { href: "/", label: "Today" },
  { href: "/review", label: "Review" },
  { href: "/activity", label: "Activity" },
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
