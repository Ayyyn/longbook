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
          <div className="price-card">
            <div className="amount">{PRICING.setup}</div>
            <div className="per">one time, to set you up</div>
            <p>
              We read your history with you, check what it got right, and
              correct it before you rely on it.
            </p>
          </div>
        </div>
        <p className="muted">
          Prices are in rupees and exclude any taxes that apply. Payment is by
          cash, cheque or bank transfer, arranged by email. There is
          nothing to pay for inside the app and we never ask for card details.
        </p>
      </section>

      <section className="slab alt">
        <h2>14 days free, everything working</h2>
        <p>
          New businesses get a full 14-day trial — your real history read in,
          the daily summary arriving, every screen open. Nothing is due until
          you have seen it work on your own data.
        </p>
      </section>

      <section className="slab">
        <h2>What is included</h2>
        <ul className="plain">
          <li>
            <strong>Everything you want read</strong> — no limit on messages,
            documents or history. Six years in one go is fine.
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

      {/* Said plainly and early. An owner who finds this out in month three is
          an owner we have wasted. */}
      <section className="slab alt">
        <h2>What is not included</h2>
        <ul className="plain">
          <li>
            <strong>It never messages your customers.</strong> It writes the
            reminder; you read it and send it. Nothing goes out of this system
            to anyone you trade with, ever.
          </li>
          <li>
            <strong>It does not replace your accounting software.</strong> Your
            accountant keeps doing what they do. This is the layer before that
            — what was agreed, before it becomes a voucher.
          </li>
          <li>
            <strong>No GST filing, no e-invoicing, no e-way bills.</strong> We
            do not touch statutory filing.
          </li>
          <li>
            <strong>No billing or POS.</strong> It does not print or issue your
            invoices.
          </li>
          <li>
            <strong>No stock valuation or inventory.</strong> It knows what was
            ordered, not what is on your shelf.
          </li>
          <li>
            <strong>No payroll, and no multi-currency.</strong>
          </li>
          <li>
            <strong>It is not the final word on your figures.</strong> It reads
            with AI and AI gets things wrong. Check anything before you act on
            it — that is why every record shows its sources.
          </li>
        </ul>
      </section>

      <section className="slab">
        <h2>Stopping</h2>
        <ul className="plain">
          <li>
            Tell us and we stop billing. Monthly runs to the end of the month
            you are in.
          </li>
          <li>
            Annual prepaid is refunded pro rata for whole unused months if you
            leave in the first six.
          </li>
          <li>
            Setup fees are not refundable once the setup is done, because the
            work is done.
          </li>
          <li>
            <strong>Your records are not deleted if you stop paying.</strong>{" "}
            The screens lock; everything comes back the moment you renew. You
            can take a copy with you as a spreadsheet at any time.
          </li>
        </ul>
        <p className="muted">
          Full terms are on the <Link href="/terms">terms page</Link>.
        </p>
      </section>

      <section className="slab alt">
        <h2>Getting access</h2>
        <p>
          Access is by invite while we onboard businesses personally. Email us
          and we will tell you straight whether it fits how you work.
        </p>
        <div className="cta-row">
          <a href={CONTACT.emailHref} className="button-link">
            <button className="primary big">Email us</button>
          </a>
        </div>
        <p className="muted">
          Have a code already? <Link href="/signup">Set up your business</Link>.
        </p>
      </section>
    </PublicPage>
  );
}
