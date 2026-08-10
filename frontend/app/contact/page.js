"use client";

import Link from "next/link";
import PublicPage from "../components/PublicPage";
import { CONTACT } from "../lib/contact";

export default function Contact() {
  return (
    <PublicPage active="/contact">
      <section className="hero-public">
        <h1>Talk to us</h1>
        <p className="lede">
          There is no form. Ring, or send a message, and you will get a person.
        </p>
      </section>

      <section className="slab">
        <div className="contact-list">
          <a href={CONTACT.phoneHref} className="contact-row">
            <span className="what">Phone</span>
            <span className="value">{CONTACT.phone}</span>
          </a>
          <a
            href={CONTACT.whatsappHref}
            className="contact-row"
            target="_blank"
            rel="noreferrer"
          >
            <span className="what">WhatsApp</span>
            <span className="value">{CONTACT.phone}</span>
          </a>
          <a href={CONTACT.emailHref} className="contact-row">
            <span className="what">Email</span>
            <span className="value">{CONTACT.email}</span>
          </a>
        </div>
        <p className="muted">{CONTACT.hours}.</p>
      </section>

      <section className="slab alt">
        <h2>What to ask about</h2>
        <ul className="plain">
          <li>
            <strong>Getting access.</strong> Tell us roughly how many parties
            you deal with and how much of your business happens on WhatsApp.
            We will say honestly whether it suits you.
          </li>
          <li>
            <strong>Renewing.</strong> Ring and we will take the payment and
            extend your access the same day. Your records stay safe in the
            meantime.
          </li>
          <li>
            <strong>Something looks wrong.</strong> Tell us which record and we
            will look at exactly which messages it came from.
          </li>
        </ul>
        <p className="muted">
          Have an invite code already? <Link href="/signup">Set up your business</Link>.
        </p>
      </section>
    </PublicPage>
  );
}
