"use client";

import Link from "next/link";
import PublicPage from "../components/PublicPage";
import { CONTACT, PRICING } from "../lib/contact";

export default function Pricing() {
  return (
    <PublicPage active="/pricing">
      <section className="hero-public">
        <h1>What it costs</h1>
        <p className="lede">
          One price for the whole business. No per-user charge, no per-message
          charge, nothing that gets more expensive as you get busier.
        </p>
      </section>

      <section className="slab">
        <div className="price-grid">
          <div className="price-card">
            <div className="amount">{PRICING.monthly}</div>
            <div className="per">per month</div>
            <p>Paid monthly. Stop whenever you like.</p>
          </div>
          <div className="price-card best">
            <div className="amount">{PRICING.yearly}</div>
            <div className="per">per year, paid up front</div>
            <p>About ₹667 a month — two months free.</p>
          </div>
        </div>
        <p className="muted">
          There is nothing to pay for inside the app.
        </p>
      </section>

      <section className="slab">
        <h2>What is included</h2>
        <ul className="plain">
          <li>
            <strong>Everything you want read</strong> — no limit on messages,
            documents or history.
          </li>
          <li>
            <strong>Every way of getting data in</strong>: WhatsApp chat
            exports, photos from your phone camera, PDFs and scans, Excel and
            Tally exports, voice notes, and email forwarded to your own
            Longbook address.
          </li>
          <li>
            <strong>Orders, payments, dispatches, quotes and complaints</strong>{" "}
            pulled out and written down for you.
          </li>
          <li>
            <strong>Party accounts</strong>: what each one buys, their usual
            rate, what they owe you, and how they actually pay.
          </li>
          <li>
            <strong>Overdue tracking</strong> against your own credit terms,
            not a default somebody else chose.
          </li>
          <li>
            <strong>Ask questions about your own records</strong> in plain
            language, with the source messages shown for every answer.
          </li>
          <li>
            <strong>Reminder drafts</strong> you send yourself, from your own
            number.
          </li>
          <li>
            <strong>The 7pm summary by email</strong>, every evening.
          </li>
          <li>
            <strong>Setup around your business</strong> — it works out how you
            run from your own messages and uses your words on screen.
          </li>
          <li>
            <strong>Every decision logged</strong>, so you can always see why
            it wrote what it wrote.
          </li>
          <li>
            <strong>Support by email</strong> from a person who knows your
            business.
          </li>
        </ul>
      </section>


      <section className="slab alt">
        <h2>Getting access</h2>
        <p>
          Initially we are helping set up every business personally, so access
          is by invite. Tell us about your business and how you keep track of
          it today. We will reach out to you very soon!
        </p>
        <div className="cta-row">
          <a href={CONTACT.emailHref} className="button-link">
            <button className="primary big">Email us</button>
          </a>
        </div>
        <p className="muted">
          Have a code already? <Link href="/login">Set up your business</Link>.
        </p>
      </section>
    </PublicPage>
  );
}
