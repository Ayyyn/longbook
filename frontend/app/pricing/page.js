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
          One price. No per-user charge, no per-message charge, nothing that
          gets more expensive as your business gets busier.
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
            <p>Works out to about ₹667 a month — two months free.</p>
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
          Payment is by cash, cheque or bank transfer, in person or over the
          phone. There is nothing to pay for inside the app and we never ask
          for card details.
        </p>
      </section>

      <section className="slab alt">
        <h2>What is included</h2>
        <ul className="plain">
          <li>Every chat you want read — no limit on messages or history.</li>
          <li>Orders, payments, dispatches, quotes and complaints, extracted for you.</li>
          <li>Party accounts: what each one buys, their usual rate, what they owe, how they pay.</li>
          <li>Overdue tracking against your own credit terms.</li>
          <li>Reminder drafts you send yourself, from your own number.</li>
          <li>The daily 7pm summary by email.</li>
          <li>Every decision logged, so you can always see why it wrote what it wrote.</li>
          <li>Setup, correction and support by phone from a person who knows your business.</li>
        </ul>
      </section>

      {/* Said plainly and early. A trader who finds this out in month three is
          a trader we have wasted. */}
      <section className="slab">
        <h2>What is not included</h2>
        <ul className="plain">
          <li>
            <strong>It never messages your customers.</strong> It writes the
            reminder; you read it and send it. Nothing goes out of this system
            to anyone you trade with, ever.
          </li>
          <li>
            <strong>It does not replace Tally.</strong> Your accountant keeps
            doing what they do. This is the layer before that — what was
            agreed on WhatsApp, before it becomes a voucher.
          </li>
          <li>
            <strong>No GST filing, no e-invoicing, no e-way bills.</strong> We
            do not touch statutory filing.
          </li>
          <li>
            <strong>No billing or POS.</strong> It does not print your invoices.
          </li>
          <li>
            <strong>No stock valuation or inventory.</strong> It knows what was
            ordered, not what is on your shelf.
          </li>
          <li>
            <strong>No payroll, and no multi-currency.</strong>
          </li>
        </ul>
      </section>

      <section className="slab alt">
        <h2>Getting access</h2>
        <p>
          Access is by invite while we onboard businesses personally. Ring us
          and we will tell you straight whether it fits how you work.
        </p>
        <div className="cta-row">
          <a href={CONTACT.phoneHref} className="button-link">
            <button className="primary big">Call {CONTACT.phone}</button>
          </a>
          <a href={CONTACT.whatsappHref} className="button-link" target="_blank" rel="noreferrer">
            <button className="big">WhatsApp us</button>
          </a>
        </div>
        <p className="muted">
          Have a code already? <Link href="/signup">Set up your business</Link>.
        </p>
      </section>
    </PublicPage>
  );
}
