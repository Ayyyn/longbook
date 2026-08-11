"use client";

import Link from "next/link";
import PublicPage from "../components/PublicPage";
import { CONTACT } from "../lib/contact";

export default function About() {
  return (
    <PublicPage active="/about">
      <section className="hero-public">
        <h1>Why we built this</h1>
      </section>

      <section className="slab">
        <p>
          Every trader we know runs their business on WhatsApp. The
          orders are there, the rates are there, the payment confirmations are
          there, the complaints are there. And then at the end of the month
          somebody sits down and tries to remember all of it.
        </p>
        <p>
          The work is not hard. It is just endless: scrolling back to find what
          rate you agreed with someone in March, working out who has crossed
          their credit days, remembering that a party still owes for two bills
          from before Diwali. That is a couple of hours a day of a person who
          should be selling.
        </p>
        <p>
          So we built something that reads the chats and writes it down.
          Nothing changes for your customers — they message you the way they
          always have. Nothing changes for your accountant. What changes is
          that you stop being the database.
        </p>
      </section>

      <section className="slab alt">
        <h2>How we work</h2>
        <p>
          We set up every business ourselves, in person. We read your history
          with you and show you exactly what it got right and what it got
          wrong, because a system you cannot check is a system you should not
          trust with your money.
        </p>
        <p>
          When it is not sure about something, it asks you rather than guessing
          — and every record shows you the messages it came from, so you can
          always see why it says what it says.
        </p>
        <p>
          We are a small team in Surat. When you ring, you get someone who
          knows your account.
        </p>
      </section>

      <section className="slab">
        <h2>Talk to us</h2>
        <div className="cta-row">
          <a href={CONTACT.phoneHref} className="button-link">
            <button className="primary big">Call {CONTACT.phone}</button>
          </a>
          <Link href="/pricing" className="button-link">
            <button className="big">See pricing</button>
          </Link>
        </div>
      </section>
    </PublicPage>
  );
}
