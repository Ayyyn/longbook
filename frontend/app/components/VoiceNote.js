"use client";

import { useEffect, useRef, useState } from "react";

// Records straight to a file and hands it back. No transcription in the
// browser: the audio goes to Gemini as audio, which is the whole point when
// the recording is Gujarati and Hindi with English quality codes in the
// middle — a separate ASR step would flatten exactly the words that matter.
//
// Chrome records webm/opus and Firefox ogg/opus, so the chosen type travels
// with the file rather than being assumed later.
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

export default function VoiceNote({ onRecorded, label = "Record a voice note", hint }) {
  const [state, setState] = useState("idle"); // idle | recording | ready | denied
  const [seconds, setSeconds] = useState(0);
  const [clip, setClip] = useState(null);
  const recorder = useRef(null);
  const chunks = useRef([]);
  const stream = useRef(null);
  const timer = useRef(null);

  useEffect(() => () => stop(true), []);

  function release() {
    clearInterval(timer.current);
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }

  async function start() {
    setClip(null);
    chunks.current = [];
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setState("denied");
      return;
    }
    const type = pickType();
    const rec = new MediaRecorder(stream.current, type ? { mimeType: type } : undefined);
    recorder.current = rec;
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    rec.onstop = () => {
      const actual = rec.mimeType || type || "audio/ogg";
      const blob = new Blob(chunks.current, { type: actual });
      release();
      if (!blob.size) {
        setState("idle");
        return;
      }
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      const file = new File([blob], `voice-note-${stamp}.${extensionFor(actual)}`, {
        type: actual,
      });
      setClip({ file, url: URL.createObjectURL(blob) });
      setState("ready");
    };
    rec.start();
    setSeconds(0);
    setState("recording");
    timer.current = setInterval(() => setSeconds((s) => s + 1), 1000);
  }

  // `discard` separates "I have finished speaking" from "forget this" — the
  // second is the one people need and the one that usually is not built.
  function stop(discard = false) {
    clearInterval(timer.current);
    if (recorder.current && recorder.current.state !== "inactive") {
      if (discard) recorder.current.onstop = () => release();
      recorder.current.stop();
    } else {
      release();
    }
    if (discard) {
      chunks.current = [];
      setClip(null);
      setState("idle");
    }
  }

  const mmss = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(
    seconds % 60,
  ).padStart(2, "0")}`;

  if (state === "denied") {
    return (
      <div className="card">
        <div className="banner error" style={{ margin: 0 }}>
          The microphone is blocked. Allow it in your browser settings, then
          try again.
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <label style={{ fontWeight: 600 }}>{label}</label>
      {hint && <p className="muted">{hint}</p>}

      {state === "idle" && (
        <div className="actions">
          <button className="primary" style={{ width: "100%" }} onClick={start}>
            ● Start recording
          </button>
        </div>
      )}

      {state === "recording" && (
        <>
          <div className="recording">
            <span className="rec-dot" />
            <span className="rec-time">{mmss}</span>
            <span className="muted">Listening…</span>
          </div>
          <div className="actions">
            <button onClick={() => stop(true)}>Cancel</button>
            <button className="primary" onClick={() => stop(false)}>
              Stop
            </button>
          </div>
        </>
      )}

      {state === "ready" && clip && (
        <>
          <audio controls src={clip.url} style={{ width: "100%", marginTop: 8 }} />
          <div className="actions">
            <button
              onClick={() => {
                URL.revokeObjectURL(clip.url);
                setClip(null);
                setState("idle");
              }}
            >
              Discard
            </button>
            <button className="primary" onClick={() => onRecorded(clip.file)}>
              Use this
            </button>
          </div>
          <p className="muted" style={{ marginBottom: 0 }}>
            Speak as you would to your munim — Hindi, Gujarati, Marathi or
            English, or all of them in one sentence.
          </p>
        </>
      )}
    </div>
  );
}
