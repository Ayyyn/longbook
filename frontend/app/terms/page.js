"use client";

import Link from "next/link";
import PublicPage from "../components/PublicPage";
import { CONTACT, PRICING } from "../lib/contact";

// The point of this page is that nobody is surprised later. The limits are
// stated as plainly as the promises, because an owner who discovers in month
// three that we do not file GST is an owner we should never have signed.
export default function Terms() {
  return (
    <PublicPage>
      <section className="hero-public">
        <h1>Terms of use</h1>
        <p className="lede">
          What you get, what you do not, and what happens if either of us wants
          to stop.
        </p>
      </section>

      <section className="slab">
        <h2>What the service does</h2>
        <p>
          Longbook reads WhatsApp chat exports, documents and photographs
          that you give it, and writes down what it finds: orders, payments,
          dispatches, quotes, complaints, party accounts and outstandings. It
          shows you what it was unsure about so you can confirm or correct it,
          and it emails you a summary each evening.
        </p>
        <p>
          It is a record-keeping assistant. It reads what you already have and
          organises it.
        </p>
      </section>

      <section className="slab alt">
        <h2>What it does not do</h2>
        <ul className="plain">
          <li>
            <strong>It is not a replacement for Tally or your accountant.</strong>{" "}
            It does not produce statutory books, ledgers for audit, or anything
            your accountant can file from directly. It sits before that: what
            was agreed on WhatsApp, before it becomes a voucher.
          </li>
          <li>
            <strong>No GST filing, e-invoicing or e-way bills.</strong> We do
            not touch statutory compliance in any form.
          </li>
          <li>
            <strong>No financial, tax or legal advice.</strong> Nothing the
            system shows you is advice. A flag saying a rate looks low or a
            party is slow to pay is an observation about your own data, not a
            recommendation about what to do.
          </li>
          <li>
            <strong>No invoicing, billing or POS.</strong> It does not print or
            issue your bills.
          </li>
          <li>
            <strong>No inventory or stock valuation.</strong> It knows what was
            ordered, not what is on your shelf.
          </li>
          <li>
            <strong>It never contacts your customers.</strong> Reminder drafts
            are yours to read, change and send.
          </li>
        </ul>
      </section>

      <section className="slab">
        <h2>Checking the figures is your job</h2>
        <p>
          This is the most important paragraph on the page.
        </p>
        <p>
          The system reads messages using AI, and <strong>AI gets things
          wrong</strong>. It will occasionally misread a rate, attach an order
          to the wrong party, or miss a payment mentioned in passing. That is
          why every record shows you the messages it came from, and why
          anything it is unsure about waits for you in Review.
        </p>
        <p>
          <strong>You are responsible for checking any figure before you act on
          it.</strong> Before you chase a payment, send a reminder, price an
          order or settle an account, verify it against your own records. Do
          not treat what you see here as the final word on what someone owes
          you.
        </p>
        <p>
          We are not liable for losses arising from acting on a figure without
          checking it — a payment chased that was already made, an order priced
          from a misread rate, a reminder sent to the wrong party. Our total
          liability to you in any case is limited to the fees you have paid us
          in the previous twelve months.
        </p>
      </section>

      <section className="slab alt">
        <h2>What it costs</h2>
        <p>
          <strong>{PRICING.monthly}</strong> per month, or{" "}
          <strong>{PRICING.yearly}</strong> for a year paid up front, plus{" "}
          <strong>{PRICING.setup}</strong> once for setup. Prices are in Indian
          rupees and exclude any taxes that apply.
        </p>
        <p>
          Payment is taken in person or by bank transfer. There is nothing to
          pay for inside the app, and we never ask for card details. Your access
          is extended by hand once payment is received.
        </p>
        <p>
          <strong>New businesses get a 14-day trial</strong> with everything
          working, before anything is due.
        </p>
        <p>
          If we change the price, existing customers keep theirs for the term
          already paid, and we tell you at least 30 days before a renewal at a
          new rate. <Link href="/pricing">Full pricing</Link>.
        </p>
      </section>

      <section className="slab">
        <h2>Stopping</h2>
        <ul className="plain">
          <li>
            <strong>You can stop whenever you like.</strong> Tell us and we stop
            billing. Monthly means you are paid up to the end of the month you
            are in.
          </li>
          <li>
            <strong>Annual prepaid is refunded pro rata</strong> for whole
            unused months if you leave in the first six months. After that it
            runs to the end of the year.
          </li>
          <li>
            <strong>Setup fees are not refundable</strong> once we have done the
            setup, because the work is done.
          </li>
          <li>
            <strong>Your data is not deleted when you stop.</strong> It is kept
            for 90 days in case you come back, then removed. Ask sooner and we
            delete it within seven days.
          </li>
          <li>
            <strong>You can take your data with you</strong> at any point, as a
            spreadsheet. Just ask.
          </li>
        </ul>
        <p>
          We may end the service if fees go unpaid after we have asked, or if
          the service is used for something unlawful. We would write to you first.
        </p>
      </section>

      <section className="slab alt">
        <h2>What we ask of you</h2>
        <ul className="plain">
          <li>
            Only upload chats and documents from <strong>your own
            business</strong> — conversations you are a party to, and records
            you have the right to hold.
          </li>
          <li>
            <strong>Keep your access token to yourself.</strong> Anyone holding
            it can see your books. Tell us at once if it is lost and we will
            issue a new one, which stops the old one working.
          </li>
          <li>
            Do not try to break into other businesses&apos; data, or resell the
            service as your own.
          </li>
        </ul>
      </section>

      <section className="slab">
        <h2>Availability</h2>
        <p>
          We aim to keep the service running during working hours and will fix
          breakages as fast as we reasonably can, but we do not promise an
          uptime figure and we are a small team. Reading a long history takes
          minutes, not seconds, and depends on a Google service we do not
          control.
        </p>
        <p>
          Your records are backed up daily. If we lose data through our own
          fault, we will tell you.
        </p>
      </section>

      <section className="slab alt">
        <h2>The legal bits</h2>
        <p>
          These terms are governed by Indian law, and the courts of Gujarat
          have jurisdiction. If any part of this page is unenforceable, the
          rest still stands.
        </p>
        <p>
          If we change these terms materially, we will tell you by email before
          the change takes effect.
        </p>
        <p>
          How we handle your data is set out separately in the{" "}
          <Link href="/privacy">privacy policy</Link>, which is part of these
          terms.
        </p>
        <p>
          Questions go to a person:{" "}
          <a href={CONTACT.emailHref}>{CONTACT.email}</a> or{" "}
          <a href={CONTACT.emailHref}>{CONTACT.email}</a>.
        </p>
        <p className="muted">Last updated 10 August 2026.</p>
      </section>
    </PublicPage>
  );
}
