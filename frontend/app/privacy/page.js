"use client";

import PublicPage from "../components/PublicPage";
import { CONTACT } from "../lib/contact";

// Written to be read, not to be survived. A trader may genuinely open this
// before handing over six years of their chats, and everything in it is
// checkable against what the system does — no "may", no "including but not
// limited to", no reserved right to change our minds about selling their data.
export default function Privacy() {
  return (
    <PublicPage>
      <section className="hero-public">
        <h1>What we do with your data</h1>
        <p className="lede">
          You are handing us your order book. This page says exactly what
          happens to it, in words we are willing to be held to.
        </p>
      </section>

      <section className="slab">
        <h2>The short version</h2>
        <ul className="plain">
          <li>
            <strong>We never message your customers.</strong> Not
            automatically, not ever. The system writes reminders; you read them
            and send them yourself from your own number.
          </li>
          <li>
            <strong>Your rates, amounts and party names are never shared</strong>{" "}
            with anyone — not other customers, not advertisers, not data
            brokers. We do not sell data. There is no version of this business
            where we do.
          </li>
          <li>
            <strong>Your data is not used to train anyone&apos;s AI.</strong>{" "}
            Not ours, not Google&apos;s.
          </li>
          <li>
            <strong>Everything is stored in India</strong>, in Google
            Cloud&apos;s Mumbai region.
          </li>
          <li>
            <strong>Ask and we delete it.</strong> All of it, within seven days.
          </li>
        </ul>
      </section>

      <section className="slab alt">
        <h2>What we collect, and why</h2>
        <p>Only what is needed to keep your books. Specifically:</p>
        <ul className="plain">
          <li>
            <strong>WhatsApp chat exports you upload.</strong> The full
            transcript, and any photos or voice notes inside a zip. This is the
            raw material — orders, payments and rates are read out of it.
          </li>
          <li>
            <strong>Documents and photos you add</strong> — bills, challans,
            purchase orders, Tally or Excel exports. Read for the figures on
            them.
          </li>
          <li>
            <strong>What is extracted from those</strong>: party names and
            phone numbers, qualities, quantities, rates, amounts, payment dates,
            dispatch details, outstandings. This is the product.
          </li>
          <li>
            <strong>Your own details</strong>: business name, your name, phone
            number, email, city. Used to sign you in and to send your daily
            summary.
          </li>
          <li>
            <strong>A record of every decision the system makes</strong> — which
            agent read what, how confident it was, how long it took, what it
            cost. This is how you can always check why a record says what it
            says.
          </li>
        </ul>
        <p>
          We do not ask for and cannot accept card or bank details. Payment is
          taken in person.
        </p>
      </section>

      <section className="slab">
        <h2>Where it is stored</h2>
        <p>
          All of it in <strong>Google Cloud&apos;s Mumbai region
          (asia-south1)</strong> — the database, the photos and documents, and
          the decision logs. It does not leave India at rest.
        </p>
        <p>
          The database is not reachable from the public internet. Photos and
          documents sit in private storage with no public links. Your access
          token is stored only as a one-way hash, which is why we cannot look
          it up for you if it is lost — we can only issue a new one.
        </p>
      </section>

      <section className="slab alt">
        <h2>Who can see it</h2>
        <ul className="plain">
          <li>
            <strong>You</strong>, through the app, using your own token.
          </li>
          <li>
            <strong>Us</strong> — the two people who run Textile Ops — when we
            are setting you up, or when you ring with a problem and we need to
            look at the record you are asking about. We look because you asked
            us to, not routinely.
          </li>
          <li>
            <strong>Nobody else.</strong> Other customers cannot see your data;
            every record is locked to your business at the database level, not
            by convention.
          </li>
        </ul>
        <p>
          If a court or the law obliges us to hand something over, we will tell
          you unless we are legally barred from doing so.
        </p>
      </section>

      <section className="slab">
        <h2>The AI part, honestly</h2>
        <p>
          Reading your messages is done by <strong>Google&apos;s Gemini</strong>,
          through the paid Gemini API. Your messages are sent to Google to be
          read, and this is the one place your data is processed by a company
          other than us. So it matters what their terms say:
        </p>
        <ul className="plain">
          <li>
            On the <strong>paid tier</strong>, which is what we use, Google does
            not use what we send to improve or train their models, and does not
            make it available to anyone else.
          </li>
          <li>
            The <strong>free tier is different</strong> — inputs there can be
            used for improving Google&apos;s products. We do not use the free
            tier, and we will not move to it.
          </li>
          <li>
            Google retains prompts briefly for abuse monitoring and then
            deletes them, per their API terms.
          </li>
          <li>
            <strong>We do not train any model of our own on your data.</strong>{" "}
            Not on your rates, not on your party relationships, not in
            aggregate with other customers&apos; data.
          </li>
        </ul>
        <p>
          If Google changes those terms in a way that matters, we will tell you
          before it takes effect, not after.
        </p>
      </section>

      <section className="slab alt">
        <h2>What we never do</h2>
        <ul className="plain">
          <li>
            <strong>Message your customers.</strong> The system has no ability
            to send anything to anyone you trade with. Reminders are drafts you
            send yourself. This is built into how it works, not a policy we
            could quietly change.
          </li>
          <li>
            <strong>Sell, rent or share your commercial terms.</strong> What you
            charge, who owes you, and who you buy from stays yours.
          </li>
          <li>
            <strong>Use your data to help a competitor of yours.</strong> We do
            not build benchmarks, market rates or industry reports out of
            customer data.
          </li>
          <li>
            <strong>Advertise to you, or let anyone else advertise to you.</strong>
          </li>
        </ul>
      </section>

      <section className="slab">
        <h2>Keeping and deleting</h2>
        <p>
          We keep your data for as long as you are a customer, and for{" "}
          <strong>90 days after that</strong> — because people come back, and
          re-reading six years of chats is not something you should have to do
          twice. After 90 days it is deleted.
        </p>
        <p>
          <strong>If your subscription lapses, nothing is deleted.</strong> You
          are locked out of the screens; the records stay exactly as they were
          and come back the moment you renew.
        </p>
        <p>
          <strong>To have it deleted sooner, just ask.</strong> Ring{" "}
          <a href={CONTACT.phoneHref}>{CONTACT.phone}</a> or email{" "}
          <a href={CONTACT.emailHref}>{CONTACT.email}</a> and say you want your
          data removed. We will do it within seven days and confirm when it is
          done. That removes everything: messages, documents, extracted
          records, party details and logs. It cannot be undone.
        </p>
        <p>
          You can also ask for a copy of everything we hold, in a spreadsheet,
          at any time.
        </p>
      </section>

      <section className="slab alt">
        <h2>If something goes wrong</h2>
        <p>
          If your data is exposed by a mistake or a breach on our side, we will
          tell you within 72 hours of finding out — what happened, what was
          affected, and what we are doing. We would rather tell you an
          embarrassing truth than have you find out later.
        </p>
      </section>

      <section className="slab">
        <h2>Changes, and who to ask</h2>
        <p>
          If we change anything on this page that affects what happens to your
          data, we will tell you by email before it takes effect. We will not
          make a material change quietly.
        </p>
        <p>
          Questions go to a person, not a form:{" "}
          <a href={CONTACT.phoneHref}>{CONTACT.phone}</a> or{" "}
          <a href={CONTACT.emailHref}>{CONTACT.email}</a>. {CONTACT.hours}.
        </p>
        <p className="muted">Last updated 10 August 2026.</p>
      </section>
    </PublicPage>
  );
}
