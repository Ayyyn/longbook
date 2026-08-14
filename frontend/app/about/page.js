"use client";

import Link from "next/link";
import PublicPage from "../components/PublicPage";
import { CONTACT } from "../lib/contact";

// Short and honest. Nobody buys because of an about page, but a few people
// refuse to buy without one — they want to know who is holding their books.
export default function About() {
  return (
    <PublicPage active="/about">
      <section className="hero-public">
        <h1>Who we are</h1>
        <p className="lede">
          Two people in Mumbai who kept watching small businesses run
          themselves brilliantly on WhatsApp and then lose track of it all by
          Friday.
        </p>
      </section>

      <section className="slab">
        <h2>Why we built it</h2>
        <p>
          The information is not missing. It is all there — the order, the
          rate, the promise to pay by the tenth, the complaint about the last
          delivery. It is just spread across four hundred messages, a few
          photographs of bills, and someone&apos;s memory.
        </p>
        <p>
          So the owner ends up doing the same work twice: once when the deal
          happens, and again at night, copying it into a book or a spreadsheet
          so it exists somewhere they can find it. Most of them are very good
          at this. All of them resent it.
        </p>
        <p>
          Every tool we looked at asked them to change how they work first —
          come off WhatsApp, enter things properly, learn the software. Nobody
          does that, and they are right not to. The way they already work is
          fast and it suits them.
        </p>
        <p>
          <strong>So we built the thing that reads instead of asking.</strong>{" "}
          You keep working exactly as you do. Longbook reads what that produces
          and keeps the books for you.
        </p>
      </section>

      <section className="slab alt">
        <h2>Why it configures itself</h2>
        <p>
          We started by looking closely at one trade, and quickly found the
          obvious trap: build for that trade and it works for that trade only.
          The next business counts in different units, bills a different way,
          and uses different words for the same thing.
        </p>
        <p>
          Writing a version per industry is a treadmill nobody wins. So the
          system reads a business&apos;s own messages, works out how that
          business runs, and asks the owner about what it actually saw. The
          questions a spare-parts supplier gets are not the questions a garment
          seller gets, and nobody wrote either set in advance.
        </p>
      </section>

      <section className="slab">
        <h2>How we work</h2>
        <ul className="plain">
          <li>
            <strong>We onboard people ourselves.</strong> We sit with you while
            it reads your history and check what it got right before you rely
            on it. That is why access is by invite — we can only do a few at a
            time properly.
          </li>
          <li>
            <strong>You get a person, not a ticket.</strong> The address below
            is read by one of the two of us, and answered the same working day
            — not by a chatbot and not by a support queue.
          </li>
          <li>
            <strong>We say what it cannot do.</strong> Plainly, on the{" "}
            <Link href="/pricing">pricing page</Link>, before you pay — not in
            month three.
          </li>
          <li>
            <strong>We do not sell your data.</strong> There is no version of
            this business where we do. It is written into the{" "}
            <Link href="/privacy">privacy page</Link> in words we are willing
            to be held to.
          </li>
        </ul>
      </section>

      <section className="slab alt">
        <h2>Built in Mumbai</h2>
        <p>
          The whole thing runs in Google Cloud&apos;s Mumbai region, which is
          also where we are. Your records do not leave the country.
        </p>
        <div className="cta-row">
          <a href={CONTACT.emailHref} className="button-link">
            <button className="primary big">Email {CONTACT.email}</button>
          </a>
        </div>
      </section>
    </PublicPage>
  );
}
