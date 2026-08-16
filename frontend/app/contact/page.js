"use client";

import Link from "next/link";
import PublicPage from "../components/PublicPage";
import { CONTACT } from "../lib/contact";

// No form. A form is a way of not answering, and it hides who you are writing
// to — which is the one thing someone handing over their order book wants to
// know. One address, read by a person rather than a queue.
export default function Contact() {
  return (
    <PublicPage active="/contact">
      <section className="hero-public">
        <h1>Talk to a person</h1>
        <p className="lede">
          There is no contact form on this page and no support queue behind it.
          Write to the address below and a person from Longbook reads it.
        </p>
        <div className="cta-row">
          <a href={CONTACT.emailHref} className="button-link">
            <button className="primary big">Email us</button>
          </a>
        </div>
      </section>

      <section className="slab">
        <h2>What to write about</h2>
        <ul className="plain">
          <li>
            <strong>Tell us about your business.</strong> Describe your
            business and how you keep track of it today. We will reach out to
            you very soon!
          </li>
          <li>
            <strong>Getting set up.</strong> Access is by invite while we
            onboard businesses personally, so this starts with a conversation.
          </li>
          <li>
            <strong>A figure that looks wrong.</strong> Send us the record and
            we will look at it with you and correct it.
          </li>
          <li>
            <strong>Getting back in.</strong> If you have lost your access
            token we can issue a new one. We cannot look up the old one — it is
            not stored in a form anyone can read, including us.
          </li>
          <li>
            <strong>Paying, or stopping.</strong> Both are arranged by email.
            There is nothing to pay for inside the app and we never ask for
            card details.
          </li>
          <li>
            <strong>Deleting your data.</strong> Ask and it is gone within
            seven days, all of it. See the{" "}
            <Link href="/privacy">privacy page</Link>.
          </li>
        </ul>
      </section>

      <section className="slab alt">
        <p className="muted">
          Already a customer? <Link href="/login">Sign in</Link>. Have a code?{" "}
          <Link href="/login">Set up your business</Link>.
        </p>
      </section>
    </PublicPage>
  );
}
