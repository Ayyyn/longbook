"use client";

import { useRef, useState } from "react";
import { api, formatNumber } from "../lib/api";

// Choosing files and sending them are two different decisions, and the gap
// between them is where people change their mind. A native <input type="file">
// gives you a read-only FileList and no way back out, so the selection is held
// in state here: files can be removed one at a time or cleared entirely, and
// the estimate re-runs on what is left.
export default function FilePicker({
  id,
  label,
  hint,
  accept,
  capture,
  onEstimate,
  children,
}) {
  const [files, setFiles] = useState([]);
  const [estimate, setEstimate] = useState(null);
  const [checking, setChecking] = useState(false);
  const inputRef = useRef(null);

  async function recheck(next) {
    setFiles(next);
    onEstimate?.(next, null);
    if (!next.length) {
      setEstimate(null);
      // Clearing the input matters: without it, re-picking the same file
      // fires no change event and the owner thinks the app has frozen.
      if (inputRef.current) inputRef.current.value = "";
      return;
    }
    setChecking(true);
    try {
      const body = await api.estimateUpload(next);
      setEstimate(body);
      onEstimate?.(next, body);
    } catch {
      // The estimate is a courtesy; never block the upload on it.
      setEstimate(null);
      onEstimate?.(next, null);
    } finally {
      setChecking(false);
    }
  }

  // Appending rather than replacing: picking a second time on a phone is how
  // people add the next chat, not how they start again.
  function add(picked) {
    const seen = new Set(files.map((f) => `${f.name}:${f.size}`));
    const merged = [...files];
    for (const f of picked) {
      if (!seen.has(`${f.name}:${f.size}`)) merged.push(f);
    }
    recheck(merged);
  }

  function human(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  return (
    <div className="card">
      <label htmlFor={id} style={{ fontWeight: 600 }}>
        {label}
      </label>
      <input
        ref={inputRef}
        id={id}
        type="file"
        accept={accept}
        {...(capture ? { capture } : {})}
        multiple
        onChange={(e) => add([...(e.target.files || [])])}
      />
      {hint && <p className="muted">{hint}</p>}

      {files.length > 0 && (
        <div className="picked">
          <div className="picked-head">
            <span>
              {files.length} {files.length === 1 ? "file" : "files"} chosen
            </span>
            <button className="link-button" onClick={() => recheck([])}>
              Clear all
            </button>
          </div>
          {files.map((f, i) => (
            <div className="picked-row" key={`${f.name}:${f.size}:${i}`}>
              <div className="picked-name">
                {f.name}
                <span className="muted"> · {human(f.size)}</span>
              </div>
              <button
                className="picked-remove"
                aria-label={`Remove ${f.name}`}
                onClick={() => recheck(files.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {checking && <p className="muted">Reading the files…</p>}

      {estimate && (
        <div className="banner" style={{ marginTop: 4 }}>
          <strong>{formatNumber(estimate.new_messages)} new</strong>
          {estimate.media > 0 && ` · ${formatNumber(estimate.media)} photos`}
          {estimate.new_messages > 0 && (
            <>
              {" "}· about {estimate.estimated_minutes} minute
              {estimate.estimated_minutes === 1 ? "" : "s"} to read
            </>
          )}
          {estimate.duplicates > 0 && (
            <> · {formatNumber(estimate.duplicates)} already read, will be skipped</>
          )}
        </div>
      )}

      {estimate?.files?.some((f) => f.error) && (
        <div className="banner error" style={{ marginTop: 8 }}>
          {estimate.files
            .filter((f) => f.error)
            .map((f) => (
              <div key={f.filename}>
                {f.filename}: {f.error}
              </div>
            ))}
          The rest will still be read.
        </div>
      )}

      {children}
    </div>
  );
}
