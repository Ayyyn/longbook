"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, signup, setToken, setPhone } from "../lib/api";
import PublicPage from "../components/PublicPage";
import { CONTACT } from "../lib/contact";

// The whole of self-serve onboarding, in the order an owner does it. Each step
// is one screenful on a phone: a step that scrolls is a step people abandon.
const STEPS = ["Your business", "About your trade", "Your WhatsApp history", "Done"];

// The Configurator reads these answers as prose, so they are questions an
// owner can answer out loud rather than fields to be filled correctly.
const TRADE_QUESTIONS = [
  {
    key: "segments",
    q: "What kind of business is this?",
    type: "multi",
    options: ["wholesaler", "retail"],
    hint: "Pick both if you do both.",
  },
  {
    key: "what_you_sell",
    q: "What do you sell?",
    type: "text",
    placeholder: "cotton shirting, 60x60 and 40x40, mostly greige",
    hint: "In your own words — qualities, counts, whatever you'd tell a new buyer.",
  },
  {
    key: "units",
    q: "What do you sell it by?",
    type: "text",
    placeholder: "meter, thaan",
    hint: "The units you quote in.",
  },
  {
    key: "tracks_lots",
    q: "Do you track dye lots or batch numbers?",
    type: "bool",
    hint: "Say no if lot numbers never come up in your messages.",
  },
  {
    key: "gives_credit",
    q: "Do you give credit?",
    type: "bool",
    hint: "Do buyers pay after delivery rather than upfront?",
  },
  {
    key: "credit_days",
    q: "How many days credit, normally?",
    type: "number",
    placeholder: "45",
    hint: "Leave blank if it varies. Used to decide who is overdue.",
    onlyIf: (a) => a.gives_credit === true,
  },
  {
    key: "rate_negotiated",
    q: "Are rates negotiated per order, or mostly fixed?",
    type: "choice",
    options: ["Negotiated each time", "Mostly fixed"],
    hint: "Tells us whether a rate that moves is normal or worth flagging.",
  },
  {
    key: "dispatch_how",
    q: "How do goods usually go out?",
    type: "text",
    placeholder: "transport, LR sent on WhatsApp",
    hint: "Courier, transport, customer pickup — however you send them.",
  },
  {
    key: "notes",
    q: "Anything else we should know?",
    type: "text",
    placeholder: "job work for two mills; PO numbers matter",
    hint: "Optional.",
  },
];

export default function SignupPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [code, setCode] = useState("");
  const [details, setDetails] = useState({
    business_name: "",
    owner_name: "",
    owner_phone: "",
    owner_email: "",
    city: "",
  });
  const [answers, setAnswers] = useState({ segments: [] });
  const [created, setCreated] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  async function createBusiness() {
    setBusy(true);
    setError(null);
    try {
      const body = await signup(code, details);
      // Sign in immediately: the owner should never have to copy their own
      // token from one screen into another to finish setting up.
      setToken(body.token);
      setPhone(details.owner_phone);
      setCreated(body);
      setStep(1);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadAndConfigure(file, partyFile) {
    setBusy(true);
    setError(null);
    try {
      if (file) {
        setNote("Reading your chat export…");
        await api.uploadSample(file);
      }
      if (partyFile) {
        setNote("Importing your party list…");
        await api.uploadIngest(partyFile);
      }
      setNote("Working out how your business runs…");
      await api.configure({
        segments: answers.segments?.length ? answers.segments : ["wholesaler"],
        what_you_sell: answers.what_you_sell || null,
        units: answers.units || null,
        tracks_lots: answers.tracks_lots ?? null,
        gives_credit: answers.gives_credit ?? null,
        credit_days: answers.credit_days ? Number(answers.credit_days) : null,
        notes: [answers.notes, answers.rate_negotiated, answers.dispatch_how]
          .filter(Boolean)
          .join("; ") || null,
      });
      setNote(null);
      setStep(3);
    } catch (err) {
      setNote(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicPage>
      <header className="bar">
        <h1>Set up your business</h1>
        <div className="sub">
          Step {step + 1} of {STEPS.length} · {STEPS[step]}
        </div>
      </header>

      <div className="progress-track" style={{ marginBottom: 4 }}>
        <div
          className="progress-fill"
          style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
        />
      </div>

      {error && <div className="banner error">{error}</div>}
      {note && <div className="banner">{note}</div>}

      {step === 0 && (
        <BusinessStep
          code={code}
          setCode={setCode}
          details={details}
          setDetails={setDetails}
          busy={busy}
          onNext={createBusiness}
        />
      )}

      {step === 1 && (
        <TradeStep
          answers={answers}
          setAnswers={setAnswers}
          onNext={() => setStep(2)}
        />
      )}

      {step === 2 && (
        <HistoryStep busy={busy} onSubmit={uploadAndConfigure} />
      )}

      {step === 3 && created && (
        <DoneStep
          created={created}
          phone={details.owner_phone}
          saved={saved}
          setSaved={setSaved}
          onFinish={() => router.replace("/today")}
        />
      )}

      {step === 0 && (
        <p className="muted" style={{ textAlign: "center" }}>
          Already set up? <Link href="/login">Sign in</Link>
        </p>
      )}
    </PublicPage>
  );
}

function BusinessStep({ code, setCode, details, setDetails, busy, onNext }) {
  const fields = [
    ["business_name", "Business name", "Ravi Fabrics", true],
    ["owner_name", "Your name", "", false],
    ["owner_phone", "Your phone number", "98765 43210", true],
    ["owner_email", "Your email", "you@business.in", false],
    ["city", "City", "Surat", false],
  ];
  const ready = code.trim() && details.business_name.trim() && details.owner_phone.trim();

  return (
    <>
      <div className="know">
        <h3>You need an invite code</h3>
        <p style={{ margin: "8px 0 0", lineHeight: 1.6 }}>
          We are not open to everyone yet. We set up each business ourselves —
          we read your chats with you and check what the system got right
          before you rely on it — so we can only take a few at a time.
        </p>
        <p style={{ margin: "10px 0 0", lineHeight: 1.6 }}>
          If you have spoken to us, your code was given to you on the phone or
          by message. If you have not,{" "}
          <a href={CONTACT.phoneHref}>ring {CONTACT.phone}</a> or{" "}
          <a href={CONTACT.whatsappHref} target="_blank" rel="noreferrer">
            message us on WhatsApp
          </a>{" "}
          and we will tell you honestly whether it suits how you work.
        </p>
      </div>

      <div className="card">
        <label htmlFor="code">Invite code</label>
        <input
          id="code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="the code you were given"
          autoComplete="off"
          spellCheck={false}
        />

      {fields.map(([key, label, placeholder, required]) => (
        <div key={key}>
          <label htmlFor={key} style={{ marginTop: 14 }}>
            {label}
            {required ? "" : " (optional)"}
          </label>
          <input
            id={key}
            value={details[key]}
            placeholder={placeholder}
            type={key === "owner_phone" ? "tel" : key === "owner_email" ? "email" : "text"}
            onChange={(e) => setDetails({ ...details, [key]: e.target.value })}
            autoComplete="off"
          />
        </div>
      ))}

      <p className="muted">
        Your phone number is how you sign in. Your email is where the daily
        summary goes.
      </p>

        <div className="actions">
          <button className="primary" style={{ width: "100%" }} disabled={busy || !ready} onClick={onNext}>
            {busy ? "Creating…" : "Continue"}
          </button>
        </div>
      </div>
    </>
  );
}

function TradeStep({ answers, setAnswers, onNext }) {
  const set = (key, value) => setAnswers({ ...answers, [key]: value });
  const visible = TRADE_QUESTIONS.filter((q) => !q.onlyIf || q.onlyIf(answers));

  return (
    <>
      <p className="muted">
        Nine quick questions. They decide what the system looks for in your
        messages — you can change any of it later.
      </p>

      {visible.map((q) => (
        <div className="card" key={q.key}>
          <label htmlFor={q.key} style={{ fontWeight: 600 }}>{q.q}</label>

          {q.type === "text" && (
            <input
              id={q.key}
              value={answers[q.key] || ""}
              placeholder={q.placeholder}
              onChange={(e) => set(q.key, e.target.value)}
            />
          )}

          {q.type === "number" && (
            <input
              id={q.key}
              type="number"
              inputMode="numeric"
              value={answers[q.key] || ""}
              placeholder={q.placeholder}
              onChange={(e) => set(q.key, e.target.value)}
            />
          )}

          {q.type === "bool" && (
            <div className="filters">
              {[["Yes", true], ["No", false]].map(([label, value]) => (
                <button
                  key={label}
                  className={answers[q.key] === value ? "primary" : ""}
                  onClick={() => set(q.key, value)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {q.type === "choice" && (
            <div className="filters">
              {q.options.map((option) => (
                <button
                  key={option}
                  className={answers[q.key] === option ? "primary" : ""}
                  onClick={() => set(q.key, option)}
                >
                  {option}
                </button>
              ))}
            </div>
          )}

          {q.type === "multi" && (
            <div className="filters">
              {q.options.map((option) => {
                const on = (answers.segments || []).includes(option);
                return (
                  <button
                    key={option}
                    className={on ? "primary" : ""}
                    onClick={() =>
                      set(
                        "segments",
                        on
                          ? answers.segments.filter((v) => v !== option)
                          : [...(answers.segments || []), option],
                      )
                    }
                  >
                    {option}
                  </button>
                );
              })}
            </div>
          )}

          <p className="muted" style={{ marginBottom: 0 }}>{q.hint}</p>
        </div>
      ))}

      <div className="actions">
        <button className="primary" style={{ width: "100%" }} onClick={onNext}>
          Continue
        </button>
      </div>
    </>
  );
}

// The step owners get stuck on, so the instructions are the screen rather than
// a link off it.
function HistoryStep({ busy, onSubmit }) {
  const [file, setFile] = useState(null);
  const [partyFile, setPartyFile] = useState(null);

  return (
    <>
      <div className="know">
        <h3>How to export a WhatsApp chat</h3>
        <ol style={{ paddingLeft: 18, lineHeight: 1.7, margin: "8px 0 0" }}>
          <li>Open the chat with a regular customer or supplier.</li>
          <li>
            Tap the contact&apos;s name at the top, then scroll down to{" "}
            <strong>Export chat</strong>.
          </li>
          <li>
            Choose <strong>Without media</strong> — it is much faster and the
            text is all we need.
          </li>
          <li>Save the file, or send it to yourself, then pick it below.</li>
        </ol>
        <p className="muted" style={{ marginBottom: 0 }}>
          On iPhone the menu is under the contact name too, near the bottom.
          Group chats work the same way.
        </p>
      </div>

      <div className="card">
        <label htmlFor="chat" style={{ fontWeight: 600 }}>Your chat export</label>
        <input
          id="chat"
          type="file"
          accept=".txt,.zip"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <p className="muted">
          A .txt or .zip from WhatsApp. One busy chat is enough to start —
          more can be added later.
        </p>
      </div>

      <div className="card">
        <label htmlFor="parties" style={{ fontWeight: 600 }}>
          Party list from Tally or Excel (optional)
        </label>
        <input
          id="parties"
          type="file"
          accept=".xlsx,.xlsm"
          onChange={(e) => setPartyFile(e.target.files?.[0] || null)}
        />
        <p className="muted">
          An export of your customers and outstandings, if you have one. It
          means names and balances are right from day one instead of being
          learned from messages.
        </p>
      </div>

      <div className="actions">
        <button
          className="primary"
          style={{ width: "100%" }}
          disabled={busy || (!file && !partyFile)}
          onClick={() => onSubmit(file, partyFile)}
        >
          {busy ? "Working…" : "Finish setup"}
        </button>
      </div>
      <p className="muted" style={{ textAlign: "center" }}>
        Nothing is sent to your customers. Ever.
      </p>
    </>
  );
}

function DoneStep({ created, phone, saved, setSaved, onFinish }) {
  const [copied, setCopied] = useState(false);

  // Sending it to their own WhatsApp is the one place this trade reliably
  // keeps things it needs to find again. "Save it somewhere safe" is not an
  // instruction most owners can act on; "message it to yourself" is.
  const digits = (phone || "").replace(/\D/g, "");
  const wa = digits.length >= 10
    ? `https://wa.me/${digits.length === 10 ? `91${digits}` : digits}?text=${encodeURIComponent(
        `Textile Ops sign-in

Phone: ${phone}
Token: ${created.token}

Keep this message.`,
      )}`
    : null;
  return (
    <>
      <div className="card">
        <h3>Your access token</h3>
        <p
          style={{
            fontFamily: "ui-monospace, monospace",
            fontSize: 16,
            wordBreak: "break-all",
            background: "var(--surface-2, #f4f4f4)",
            padding: "12px 14px",
            borderRadius: 8,
            margin: "8px 0 12px",
          }}
        >
          {created.token}
        </p>
        <div className="actions">
          <button
            className="primary"
            style={{ width: "100%" }}
            onClick={() => {
              navigator.clipboard?.writeText(created.token);
              setCopied(true);
            }}
          >
            {copied ? "Copied" : "Copy token"}
          </button>
        </div>
        {wa && (
          <div className="actions" style={{ marginTop: 10 }}>
            <a className="button-link" href={wa} target="_blank" rel="noreferrer">
              <button style={{ width: "100%" }}>Send it to my WhatsApp</button>
            </a>
          </div>
        )}

        {created.emailed_to ? (
          <div className="banner" style={{ marginTop: 12 }}>
            We have also emailed this to <strong>{created.emailed_to}</strong>.
            Keep that email — it is how you sign in on a new phone.
          </div>
        ) : (
          <div className="banner error" style={{ marginTop: 12 }}>
            Save this somewhere safe now. It is shown once and cannot be shown
            again — it is what signs you in on another phone.
          </div>
        )}
        <label
          className="line"
          style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}
        >
          <input
            type="checkbox"
            checked={saved}
            onChange={(e) => setSaved(e.target.checked)}
            style={{ width: "auto", margin: 0 }}
          />
          <span>I have saved my token.</span>
        </label>
      </div>

      <div className="actions">
        <button
          className="primary"
          style={{ width: "100%" }}
          disabled={!saved}
          onClick={onFinish}
        >
          Open my dashboard
        </button>
      </div>
      <p className="muted" style={{ textAlign: "center" }}>
        Your history is being read now. The dashboard shows progress as records
        come in.
      </p>
    </>
  );
}
