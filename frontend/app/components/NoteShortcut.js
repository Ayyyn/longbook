"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// A pencil, always within reach.
//
// The thought worth writing down never arrives while you are on the notes
// screen — it arrives while looking at an order, or halfway through the review
// queue, and by the time you have navigated there it is gone. So the way in is
// on every screen.
//
// Sits above the tab bar rather than beside it: the bar is already five items
// wide on a phone, and a sixth would shrink all of them.
const HIDDEN_ON = [
  "/login", "/signup", "/recover", "/onboarding",
  "/privacy", "/terms", "/pricing", "/contact", "/notes",
];

export default function NoteShortcut() {
  const pathname = usePathname();
  if (pathname === "/") return null;
  if (HIDDEN_ON.some((p) => pathname.startsWith(p))) return null;

  return (
    <Link href="/notes" className="note-shortcut" aria-label="Write a note">
      <span aria-hidden="true">✎</span>
    </Link>
  );
}
