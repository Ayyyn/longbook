"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

// Dictation into a text box, not a recording to keep.
//
// The version this replaces stopped and offered a player, a Discard and a Use
// this. That is the right shape for attaching a recording to something; it is
// the wrong shape for speaking instead of typing, which is what a mic beside a
// text box promises. Nobody wants to listen back to their own question — they
// want the words in the box so they can fix the one the model misheard. So on
// stop it transcribes and hands the text straight over.
//
// Correction stays with the owner, which is the whole reason the text lands in
// an editable box rather than being acted on: dictation across Hindi, Gujarati
// and English with quality codes in the middle is wrong often enough that
// acting on the first attempt puts words in their mouth.

const TYPES = [
  "audio/ogg;codecs=opus",
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
];

function pickType() {
  if (typeof MediaRecorder === "undefined") return null;
  return TYPES.find((t) => MediaRecorder.isTypeSupported(t)) || null;
}

function extensionFor(type) {
  if (!type) return "ogg";
  if (type.startsWith("audio/ogg")) return "ogg";
  if (type.startsWith("audio/webm")) return "webm";
  if (type.startsWith("audio/mp4")) return "m4a";
  return "ogg";
}

// One standard glyph, drawn rather than an emoji: 🎤 renders as a different
// object on every platform and picks up its own colour, which is exactly the
// thing that made it invisible against the bar on some phones.
function MicIcon({ on }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"
         fill="none" stroke="currentColor" strokeWidth="1.9"
         strokeLinecap="round" strokeLinejoin="round">
      {on ? (
        <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none" />
      ) : (
        <>
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0" />
          <path d="M12 18v3" />
        </>
      )}
    </svg>
  );
}

export default function Dictate({ onText, onError, className = "" }) {
  const [state, setState] = useState("idle"); // idle | recording | working | denied
  const recorder = useRef(null);
  const chunks = useRef([]);
  const stream = useRef(null);

  useEffect(() => () => release(), []);

  function release() {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }

  async function start() {
    chunks.current = [];
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setState("denied");
      onError?.("The microphone is blocked. Allow it in your browser settings.");
      return;
    }
    const type = pickType();
    const rec = new MediaRecorder(stream.current, type ? { mimeType: type } : undefined);
    recorder.current = rec;
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    rec.onstop = async () => {
      const actual = rec.mimeType || type || "audio/ogg";
      const blob = new Blob(chunks.current, { type: actual });
      release();
      if (!blob.size) {
        setState("idle");
        return;
      }
      const file = new File([blob], `dictation.${extensionFor(actual)}`, { type: actual });
      setState("working");
      try {
        const { text } = await api.transcribeNote(file);
        // An empty transcript is silence, not a failure worth a red banner.
        if (text && text.trim()) onText(text.trim());
        else onError?.("Nothing was heard. Try again.");
      } catch (err) {
        onError?.(err.message || "Could not make out the recording.");
      } finally {
        setState("idle");
      }
    };
    rec.start();
    setState("recording");
  }

  function stop() {
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
    else release();
  }

  const busy = state === "working";
  return (
    <button
      type="button"
      className={`dictate ${state} ${className}`.trim()}
      onClick={state === "recording" ? stop : start}
      disabled={busy}
      aria-label={state === "recording" ? "Stop and use what I said" : "Speak"}
      title={state === "recording" ? "Stop" : "Speak"}
    >
      {busy ? <span className="dictate-dots" aria-hidden="true" /> : <MicIcon on={state === "recording"} />}
    </button>
  );
}
