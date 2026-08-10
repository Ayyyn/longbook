"use client";

import Link from "next/link";
import PublicPage from "./components/PublicPage";
import { CONTACT, PRICING } from "./lib/contact";

export default function Home() {
  return (
    <PublicPage active="/">
      <section className="hero-public">
        <h1>
          Your WhatsApp is already your order book.
          <br />
          We just write it down.
        </h1>
        <p className="lede">
          Orders, payments and outstandings come out of the chats you are
          already having. Nothing new for your customers to learn. Nothing to
          type twice.
        </p>
        <Link href="/pricing" className="button-link">
          <button className="primary big">See what it costs</button>
        </Link>
        <p className="muted">
          Access is by invite while we set up businesses one at a time.{" "}
          <a href={CONTACT.phoneHref}>Call {CONTACT.phone}</a>.
        </p>
      </section>

      {/* Concrete before abstract. A trader decides in the first ten seconds
          whether this is about their actual day. */}
      <section className="slab">
        <h2>What it actually does</h2>
        <ul className="plain">
          <li>
            Ashok Textiles messages <em>&ldquo;150 mtr SR-1042 bhej dena, rate
            wahi purana&rdquo;</em>. It becomes an order — quality, quantity,
            and last agreed rate — waiting for you to confirm.
          </li>
          <li>
            Someone sends <em>&ldquo;50,000 RTGS kar diya&rdquo;</em>. The
            payment goes against their account and their outstanding drops.
          </li>
          <li>
            On Tuesday morning it tells you Ashok Textiles has crossed 60 days,
            and drafts the reminder. You read it, change it if you want, and
            send it yourself from your own number.
          </li>
          <li>
            A rate 20% below what that party normally pays gets flagged before
            the goods go out, not after the bill.
          </li>
          <li>
            At 7pm you get one email: what came in, what went out, who owes
            what.
          </li>
        </ul>
      </section>

      <section className="slab alt">
        <h2>Who it is for</h2>
        <p>
          Fabric wholesalers and traders who run the business on WhatsApp and
          keep the real numbers in their head, a diary, or a hundred chats they
          have to scroll back through. If you have between twenty and a few
          hundred regular parties, this is built for you.
        </p>
        <p>
          If you already have a full office running Tally properly and nothing
          important happens on WhatsApp, you do not need this.
        </p>
      </section>

      <section className="slab">
        <h2>How it works</h2>
        <ol className="steps">
          <li>
            <strong>You send us your chats.</strong> Export a WhatsApp chat —
            it takes about thirty seconds, and we show you how. Six years of
            history is fine.
          </li>
          <li>
            <strong>It reads them.</strong> Ten minutes, and your parties,
            orders, dispatches and payments are on screen. Anything it was not
            sure about it asks you, one question at a time.
          </li>
          <li>
            <strong>You check it each morning.</strong> Confirm what is
            waiting, look at who needs chasing, get on with your day.
          </li>
        </ol>
      </section>

      <section className="slab alt">
        <h2>What it costs</h2>
        <p className="price-line">
          <strong>{PRICING.monthly}</strong> a month, or{" "}
          <strong>{PRICING.yearly}</strong> for the year paid up front.{" "}
          <strong>{PRICING.setup}</strong> once, to set you up.
        </p>
        <Link href="/pricing">See exactly what is included</Link>
      </section>

      <section className="slab">
        <h2>How to get access</h2>
        <p>
          We are not open to everyone yet. We set up each business ourselves —
          we read your chats with you, check what it got right, and fix what it
          got wrong before you rely on it. That takes a morning, and we can
          only do a few at a time.
        </p>
        <p>
          Ring or message and we will tell you honestly whether it suits your
          business. If it does, you get an invite code and we book a time.
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
          Already have an invite code? <Link href="/signup">Set up your business</Link>.
        </p>
      </section>
    </PublicPage>
  );
}
