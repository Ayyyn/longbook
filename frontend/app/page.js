"use client";

import Link from "next/link";
import PublicPage from "./components/PublicPage";
import { CONTACT, PRICING } from "./lib/contact";

// Order of argument, deliberately: interest, then proof, then difference, then
// mechanism, then trust, then the ask. Nothing explains how it works until the
// reader already wants it to. The old page led with "it reads your chats",
// which is the machinery, and reads as surveillance to someone deciding
// whether to hand over their order book.
export default function Home() {
  return (
    <PublicPage active="/">
      {/* Picture first. Nine trades in one glance says "this is for a business
          like mine" faster than any sentence, and it earns the generality the
          copy claims further down. */}
      <section className="hero-art">
        <img
          src="/businesses-1024.webp"
          srcSet="/businesses-512.webp 512w, /businesses-768.webp 768w, /businesses-1024.webp 1024w"
          sizes="(max-width: 900px) 100vw, 880px"
          width={1024}
          height={559}
          alt="Nine small businesses side by side — a jeweller, a fabric shop, a
               warehouse, a chemist, a machine works, a service desk, an
               electrical shop, a produce market and a hardware store."
          decoding="async"
          fetchPriority="high"
        />
      </section>

      <section className="hero-public">
        <h1>Your business has a lot going on. Longbook keeps up.</h1>
        <p className="lede">
          Orders, payments, customers and commitments are scattered across
          chats, bills and your own memory. Longbook helps small businesses bring them together and
          turns them into the few things worth doing today.
        </p>
        <p className="lede-sub">
          Works with the records you already keep.
        </p>
        <div className="cta-row">
          <a href={CONTACT.emailHref} className="button-link">
            <button className="primary big">Get access</button>
          </a>
          <a href="#how" className="button-link">
            <button className="big">See how it works</button>
          </a>
        </div>
        <p className="sources-line">
          WhatsApp · Tally · Excel · Email · PDFs · Photos · Voice notes
        </p>
      </section>

      {/* Proof before explanation. The figures are invented, so the card says
          so — an unlabelled sample reads as a real customer's book. */}
      <section className="slab">
        <h2>Open Longbook. Know what needs attention.</h2>
        <div className="today-card">
          <div className="today-tag">Example</div>
          <div className="today-row">
            <div className="today-figure">₹1,42,000 overdue</div>
            <div className="today-note">3 customers to follow up</div>
          </div>
          <div className="today-row">
            <div className="today-figure">2 orders, no dispatch confirmed</div>
            <div className="today-note">Last movement 9 days ago</div>
          </div>
          <div className="today-row">
            <div className="today-figure">Mahavir Textiles</div>
            <div className="today-note">
              Asking again today · last quoted ₹74/m
            </div>
          </div>
          <div className="today-more">5 things for today →</div>
        </div>
        <p className="muted">
          Not a dashboard to study. A short list to act on.
        </p>
      </section>

      <section className="slab alt">
        <h2>Things it does</h2>
        <div className="outcome-grid">
          <div className="outcome">
            <h3>Know what&apos;s pending</h3>
            <p>
              Orders waiting, payments overdue, and promises that were made but
              not kept.
            </p>
          </div>
          <div className="outcome">
            <h3>Remember every customer</h3>
            <p>
              What they buy, what you quoted, what they owe, and how they
              actually pay.
            </p>
          </div>
          <div className="outcome">
            <h3>See where the money is</h3>
            <p>
              Outstanding, ageing, and what was promised against what arrived.
            </p>
          </div>
          <div className="outcome">
            <h3>Know what to do today</h3>
            <p>
              The few things that need you, with the record behind each one.
            </p>
          </div>
        </div>
      </section>

      {/* The differentiator. Given room because it is the only part a
          competitor cannot copy by adding a feature. */}
      <section className="slab">
        <h2>Made for your business. By understanding your business.</h2>
        <p className="lede">
          Every business keeps track of different things. Longbook learns what
          matters in yours: your products, your units, your pricing, how an
          order moves, and who you chase.
        </p>
        <div className="trade-grid">
          <div className="trade">
            <h3>Fabric wholesaler</h3>
            <p>Metres · Lots · Shades · Credit</p>
          </div>
          <div className="trade">
            <h3>Machinery supplier</h3>
            <p>Models · Parts · Quotations · Service</p>
          </div>
          <div className="trade">
            <h3>Chemical distributor</h3>
            <p>Grades · Drums · Batches · Credit</p>
          </div>
        </div>
        <p className="claim">Same Longbook. Different business.</p>
      </section>

      <section className="slab alt" id="how">
        <h2>Three steps, once.</h2>
        <ol className="steps">
          <li>
            <h3>Bring the records you already use</h3>
            <p>Start with as much or as little history as you like.</p>
          </li>
          <li>
            <h3>Longbook understands your business</h3>
            <p>
              It works out what matters and asks only where it needs you. About
              five minutes.
            </p>
          </li>
          <li>
            <h3>Start each day knowing what needs attention</h3>
            <p>Orders. Payments. Customers. Follow-ups.</p>
          </li>
        </ol>
      </section>

      <section className="slab">
        <h2>See why Longbook flagged it.</h2>
        <p className="lede">
          Every suggestion comes with the record behind it. The message, the
          bill, the payment. Tap through and check it yourself.
        </p>
        <p>Where it isn&apos;t sure, it asks instead of hallucinating.</p>
      </section>

      <section className="slab alt">
        <h2>Your business stays yours.</h2>
        <p className="lede">
          Private, and never used to train AI. Longbook never
          messages your customers and never acts without you.
        </p>
        <p className="muted">
          <Link href="/privacy">How we protect your data →</Link>
        </p>
      </section>

      <section className="slab">
        <h2>Ask us whether it fits</h2>
        <p className="lede">
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
          {PRICING.monthly} a month. See <Link href="/pricing">what it costs</Link>.
          Already have a code? <Link href="/login">Set up your business</Link>.
        </p>
      </section>
    </PublicPage>
  );
}
