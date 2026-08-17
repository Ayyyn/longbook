"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import TokenGate from "../components/TokenGate";
import Dictate from "../components/Dictate";
import Empty from "../components/Empty";
import { api } from "../lib/api";

export default function NotesPage() {
  return (
    <TokenGate>
      <Notes />
    </TokenGate>
  );
}

// The owner's own words, kept as written.
//
// Everything else in this product reads what a business produces and decides
// something about it. This does not: nothing here is extracted, resolved,
// attributed to a party or queued for review. A lot of what a shop knows —
// who is taking over after Diwali, which transporter to avoid on a Friday,
// what to keep aside for a reorder — fits no schema, and until now the only
// place for it was the owner's memory, which is the thing this product exists
// to replace.
//
// Dictation is one-way on purpose: what is heard lands in the typing box for
// the owner to correct, and only what they approve is saved. Speech across
// three languages is wrong often enough that storing the first attempt would
// be putting words in their mouth.
function Notes() {
  const [notes, setNotes] = useState(null);
  const [text, setText] = useState("");
  const [caption, setCaption] = useState("");
  const [picked, setPicked] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [source, setSource] = useState("typed");
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    setNotes(await api.notes().catch(() => []));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function save() {
    if (busy || (!text.trim() && !picked)) return;
    setBusy(true);
    setError(null);
    try {
      await api.createNote({ body: text, caption, file: picked, source });
      setText("");
      setCaption("");
      setPicked(null);
      setSource("typed");
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="bar">
        <h1>Notes</h1>
        <div className="sub">Note down anything you would like to</div>
      </header>

      {error && <div className="banner error">{error}</div>}

      <div className="note-compose">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Write it down, or tap the mic and say it…"
          rows={3}
          aria-label="Your note"
        />

        {picked && (
          <div className="note-picked">
            <span>{picked.name}</span>
            <button
              className="link-button"
              onClick={() => {
                setPicked(null);
                if (fileRef.current) fileRef.current.value = "";
              }}
            >
              Remove
            </button>
          </div>
        )}

        {picked && (
          <input
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="Caption for the picture (optional)"
            aria-label="Caption"
          />
        )}

        <input
          ref={fileRef}
          type="file"
          accept="image/*,.heic,.heif"
          style={{ display: "none" }}
          onChange={(e) => setPicked(e.target.files?.[0] || null)}
        />

        <div className="note-actions">
          <button onClick={() => fileRef.current?.click()} aria-label="Attach a picture">
            📷 Picture
          </button>
          <Dictate
            onText={(heard) => {
              // Appended, not replaced: a second thought should not wipe the
              // first.
              setText((current) => (current ? `${current} ${heard}` : heard));
              setSource("voice");
            }}
            onError={setError}
          />
          <button
            className="primary"
            disabled={busy || (!text.trim() && !picked)}
            onClick={save}
          >
            {busy ? "Saving…" : "Save note"}
          </button>
        </div>

      </div>

      {notes === null ? (
        <div className="empty">Loading…</div>
      ) : notes.length === 0 ? (
        <Empty title="Nothing written down yet" />
      ) : (
        notes.map((note) => <NoteCard key={note.id} note={note} onDeleted={load} />)
      )}
    </>
  );
}

function NoteCard({ note, onDeleted }) {
  const [busy, setBusy] = useState(false);
  const when = new Date(note.created_at);
  // Date and time on every note: "did I write that before or after I rang
  // him?" is the question a note usually has to answer.
  const stamp = when.toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  });

  return (
    <div className="card note-card">
      <div className="note-when">
        {stamp}
        {note.source === "voice" && <span className="note-tag">spoken</span>}
      </div>

      {note.media_url && note.media_kind === "image" && (
        <NoteImage path={note.media_url} alt={note.caption || "Attached picture"} />
      )}
      {note.caption && <div className="note-caption">{note.caption}</div>}
      {note.body && <p className="note-body">{note.body}</p>}

      <button
        className="link-button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await api.deleteNote(note.id);
            await onDeleted();
          } finally {
            setBusy(false);
          }
        }}
      >
        Delete
      </button>
    </div>
  );
}

function NoteImage({ path, alt }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let revoked = null;
    api.fetchMedia(path)
      .then((objectUrl) => {
        revoked = objectUrl;
        setUrl(objectUrl);
      })
      .catch(() => setUrl(null));
    // Object URLs hold the blob in memory until released; a long notes list
    // would otherwise keep every picture alive for the life of the tab.
    return () => {
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [path]);

  if (!url) return <div className="note-image placeholder" aria-hidden="true" />;
  return <img className="note-image" src={url} alt={alt} />;
}
