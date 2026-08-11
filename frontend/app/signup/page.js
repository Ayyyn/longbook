"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, signup, setToken, setPhone, formatNumber } from "../lib/api";
import PublicPage from "../components/PublicPage";
import FilePicker from "../components/FilePicker";
import { CONTACT } from "../lib/contact";

// The order matters and it changed. Data comes before questions, because the
// questions are written from the data: asking "do you track batch numbers?"
// before reading anything is a guess, and asking "I can see lot numbers like
// BL-4471 in your chats — do those matter?" is not.
const STEPS = [
  "Your business",
  "Your data",
  "About your work",
  "A few more",
  "Done",
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
  const [created, setCreated] = useState(null);
  const [universal, setUniversal] = useState([]);
  const [generated, setGenerated] = useState([]);
  const [answers, setAnswers] = useState({});
  const [uploaded, setUploaded] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  // Elapsed seconds against an expected duration. A step that takes 20
  // seconds behind an unlabelled spinner is a step people tap twice or
  // abandon, and this is the moment a customer is watching over a
  // shoulder.
  const [work, setWork] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  async function createBusiness() {
    setBusy(true);
    setError(null);
    try {
      const body = await signup(code, details);
      // Signed in immediately: everything after this needs a token, and making
      // someone copy their own token between two screens of the same flow is a
      // step with no purpose.
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

  async function sendData(chats, partyFile) {
    setBusy(true);
    setError(null);
    try {
      if (chats?.length) {
        setNote(
          chats.length === 1 ? "Reading your chat…" : `Reading ${chats.length} chats…`,
        );
        setUploaded(await api.uploadSample(chats));
      }
      if (partyFile) {
        setNote("Reading your customer list…");
        await api.uploadIngest(partyFile);
      }
      setNote(null);
      const set = await api.interview("universal").catch(() => ({ questions: [] }));
      setUniversal(set.questions || []);
      setStep(2);
    } catch (err) {
      setNote(null);
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // Generated after the universal answers, so both the messages and what the
  // owner just said are available to write against.
  async function loadGenerated() {
    setBusy(true);
    setWork({
      title: "Reading your messages",
      steps: [
        "Going through what you sent",
        "Working out what we still need to ask",
      ],
      expect: 20,
    });
    try {
      const set = await api.interview("generated");
      setGenerated(set.questions || []);
    } catch {
      // Never a dead end: if generation fails, setup still finishes.
      setGenerated([]);
    } finally {
      setWork(null);
      setBusy(false);
      setStep(3);
    }
  }

  async function finish() {
    setBusy(true);
    setError(null);
    setWork({
      title: "Setting up your business",
      steps: [
        "Saving your answers",
        "Working out how your business runs",
        "Starting to read your history",
      ],
      expect: 25,
    });
    try {
      const all = [...universal, ...generated];
      const byPurpose = (purpose) =>
        all.find((q) => q.purpose === purpose && answers[q.key] != null);
      const units = byPurpose("units");
      const batch = byPurpose("batch_tracking");
      const credit = all.find(
        (q) => q.purpose === "credit_terms" && q.type === "number" && answers[q.key],
      );

      // Everything travels as prose too. The Configurator reads that, and it
      // means a question we could not map to a fixed field is not lost.
      const prose = {};
      for (const q of all) {
        const value = answers[q.key];
        if (value === null || value === undefined || value === "") continue;
        prose[q.question] = String(value);
      }

      await api.configure({
        segments: [],
        what_you_sell: answers.what_you_sell || null,
        units: units ? String(answers[units.key]) : null,
        tracks_lots:
          batch && typeof answers[batch.key] === "boolean" ? answers[batch.key] : null,
        gives_credit: null,
        credit_days: credit ? Number(answers[credit.key]) : null,
        notes: answers.what_kind || null,
        answers: prose,
      });
      setWork(null);
      setStep(4);
    } catch (err) {
      setWork(null);
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
      {work && <Working {...work} />}

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

      {step === 1 && <DataStep busy={busy} onSubmit={sendData} />}

      {step === 2 && (
        <QuestionStep
          title="Tell us about your work"
          intro="Three quick ones, then we will ask about what we found in your messages."
          questions={universal}
          answers={answers}
          setAnswers={setAnswers}
          busy={busy}
          onNext={loadGenerated}
        />
      )}

      {step === 3 && (
        <QuestionStep
          title={generated.length ? "A few more, from your own messages" : "Nearly done"}
          intro={
            generated.length
              ? "These come from what we just read, so you can correct anything we got wrong."
              : "Nothing more to ask. You can finish here."
          }
          questions={generated}
          answers={answers}
          setAnswers={setAnswers}
          busy={busy}
          nextLabel="Finish setup"
          onNext={finish}
        />
      )}

      {step === 4 && created && (
        <DoneStep
          created={created}
          phone={details.owner_phone}
          uploaded={uploaded}
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

// Says what is happening and roughly how long, and keeps moving. Anything
// over about three seconds needs this rather than a spinner.
function Working({ title, steps, expect }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // Advance through the named steps across the expected duration, then hold
  // on the last one rather than claiming to be finished.
  const index = Math.min(steps.length - 1, Math.floor(elapsed / (expect / steps.length)));
  const pct = Math.min(96, Math.round((elapsed / expect) * 100));
  const over = elapsed > expect + 5;

  return (
    <div className="empty-state working">
      <h3>{title}</h3>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="why">
        {steps[index]}…{" "}
        {over
          ? "taking longer than usual, still going"
          : `about ${Math.max(1, expect - elapsed)} seconds left`}
      </div>
      <p className="muted" style={{ marginBottom: 0 }}>
        Do not close this page.
      </p>
    </div>
  );
}

function BusinessStep({ code, setCode, details, setDetails, busy, onNext }) {
  const fields = [
    ["business_name", "Business name", "", true],
    ["owner_name", "Your name", "", false],
    ["owner_phone", "Your phone number", "98765 43210", true],
    ["owner_email", "Your email", "you@business.in", false],
    ["city", "City", "", false],
  ];
  const ready = code.trim() && details.business_name.trim() && details.owner_phone.trim();

  return (
    <>
      <div className="know">
        <h3>You need an invite code</h3>
        <p style={{ margin: "8px 0 0", lineHeight: 1.6 }}>
          We are not open to everyone yet. We set up each business ourselves,
          so we can only take a few at a time.
        </p>
        <p style={{ margin: "10px 0 0", lineHeight: 1.6 }}>
          If you have spoken to us, your code was given to you on the phone. If
          not, <a href={CONTACT.phoneHref}>ring {CONTACT.phone}</a> or{" "}
          <a href={CONTACT.whatsappHref} target="_blank" rel="noreferrer">
            message us
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
              type={
                key === "owner_phone" ? "tel" : key === "owner_email" ? "email" : "text"
              }
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
          <button
            className="primary"
            style={{ width: "100%" }}
            disabled={busy || !ready}
            onClick={onNext}
          >
            {busy ? "Creating…" : "Continue"}
          </button>
        </div>
      </div>
    </>
  );
}

// Data first. Everything after this is written from what lands here.
function DataStep({ busy, onSubmit }) {
  const [chats, setChats] = useState([]);
  const [partyFile, setPartyFile] = useState(null);
  const partyRef = useRef(null);

  return (
    <>
      <p className="muted">
        We read this first, so the questions we ask next are about your actual
        business rather than a form.
      </p>

      <div className="know">
        <h3>How to export a WhatsApp chat</h3>
        <ol style={{ paddingLeft: 18, lineHeight: 1.7, margin: "8px 0 0" }}>
          <li>Open the chat with a regular customer or supplier.</li>
          <li>
            Tap their name at the top, scroll down, tap{" "}
            <strong>Export chat</strong>.
          </li>
          <li>
            Choose <strong>Without media</strong> for text only, or{" "}
            <strong>Include media</strong> to bring the photos too.
          </li>
          <li>Save it, then repeat for your other regular customers.</li>
        </ol>
        <p className="muted" style={{ marginBottom: 0 }}>
          On iPhone the menu is under their name too. Group chats work the same
          way.
        </p>
      </div>

      <FilePicker
        id="chat"
        label="Your chat exports"
        accept=".txt,.zip"
        hint="Pick as many as you like — your suppliers, your regular buyers, your transporter."
        onEstimate={(picked) => setChats(picked)}
      />

      <div className="card">
        <label htmlFor="parties" style={{ fontWeight: 600 }}>
          Your customer list from Tally or Excel (optional)
        </label>
        <input
          ref={partyRef}
          id="parties"
          type="file"
          accept=".xlsx,.xlsm"
          onChange={(e) => setPartyFile(e.target.files?.[0] || null)}
        />
        <p className="muted">
          If you have one, names and balances are right from day one instead of
          being learned from messages.
        </p>
        {partyFile && (
          <div className="picked">
            <div className="picked-row">
              <div className="picked-name">{partyFile.name}</div>
              <button
                className="picked-remove"
                aria-label="Remove"
                onClick={() => {
                  setPartyFile(null);
                  if (partyRef.current) partyRef.current.value = "";
                }}
              >
                ×
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="actions">
        <button
          className="primary"
          style={{ width: "100%" }}
          disabled={busy || (!chats.length && !partyFile)}
          onClick={() => onSubmit(chats, partyFile)}
        >
          {busy ? "Reading…" : "Continue"}
        </button>
      </div>
      <p className="muted" style={{ textAlign: "center" }}>
        Nothing is sent to your customers. Ever.
      </p>
    </>
  );
}

// One renderer for both sets — they arrive in the same shape, and the owner
// should not be able to tell which were written for them.
function QuestionStep({
  title,
  intro,
  questions,
  answers,
  setAnswers,
  busy,
  onNext,
  nextLabel = "Continue",
}) {
  const set = (key, value) => setAnswers({ ...answers, [key]: value });

  return (
    <>
      <div className="know">
        <h3>{title}</h3>
        <p style={{ margin: "8px 0 0", lineHeight: 1.6 }}>{intro}</p>
      </div>

      {questions.map((q) => (
        <div className="card" key={q.key}>
          <label
            htmlFor={q.key}
            style={{
              fontWeight: 600,
              textTransform: "none",
              fontSize: 16,
              letterSpacing: 0,
            }}
          >
            {q.question}
          </label>

          {q.type === "text" && (
            <input
              id={q.key}
              value={answers[q.key] || ""}
              onChange={(e) => set(q.key, e.target.value)}
            />
          )}

          {q.type === "number" && (
            <input
              id={q.key}
              type="number"
              inputMode="numeric"
              value={answers[q.key] ?? ""}
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

          {q.hint && (
            <p className="muted" style={{ marginBottom: 0 }}>
              {q.hint}
            </p>
          )}
        </div>
      ))}

      <div className="actions">
        <button
          className="primary"
          style={{ width: "100%" }}
          disabled={busy}
          onClick={onNext}
        >
          {busy ? "Working…" : nextLabel}
        </button>
      </div>
      <p className="muted" style={{ textAlign: "center" }}>
        You can skip anything you are not sure about.
      </p>
    </>
  );
}

function DoneStep({ created, phone, uploaded, saved, setSaved, onFinish }) {
  const [copied, setCopied] = useState(false);
  const digits = (phone || "").replace(/\D/g, "");
  const wa =
    digits.length >= 10
      ? `https://wa.me/${digits.length === 10 ? `91${digits}` : digits}?text=${encodeURIComponent(
          `Sign-in details\n\nPhone: ${phone}\nToken: ${created.token}\n\nKeep this message.`,
        )}`
      : null;

  return (
    <>
      {uploaded?.interactions > 0 && (
        <div className="banner">
          {formatNumber(uploaded.interactions)} messages are being read now.
        </div>
      )}

      <div className="card">
        <h3>Your access token</h3>
        <p
          style={{
            fontFamily: "ui-monospace, monospace",
            fontSize: 16,
            wordBreak: "break-all",
            background: "var(--card-2)",
            padding: "12px 14px",
            borderRadius: 10,
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
            again.
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
        Your messages are being read now. The dashboard shows progress as
        records come in.
      </p>
    </>
  );
}
