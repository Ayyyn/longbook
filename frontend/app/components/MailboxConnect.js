"use client";

import { useCallback, useEffect, useState } from "react";
import { api, formatNumber } from "../lib/api";

// The connected mailbox.
//
// Leads the screen because it is the version that keeps working after the
// owner stops thinking about it — forwarding only ever carries the mail
// somebody remembered to forward.
//
// The one thing this has to be unambiguous about is what we do with the
// access: read, never send. An owner handing over their mailbox is entitled
// to know that in the same breath as the button.
export default function MailboxConnect({ dest = "add" }) {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setState(await api.mailbox().catch(() => ({ available: false, accounts: [] })));
  }, []);

  // The first pull of a mailbox with years in it does not fit in one request,
  // so the server hands back `more` and we come back for the rest. Looping
  // here rather than leaving it to the ten-minute sweep is the difference
  // between the history being there when the owner looks and being there an
  // hour later.
  //
  // Capped so a mailbox that keeps saying "more" cannot spin forever; the
  // sweep picks up anything past the cap.
  const pull = useCallback(async () => {
    setBusy("sync");
    let total = 0;
    try {
      for (let round = 0; round < 20; round += 1) {
        const out = await api.mailboxSync();
        total += out.records || 0;
        setNote(
          out.more
            ? `Reading your mail — ${formatNumber(total)} so far…`
            : total
              ? `Read ${formatNumber(total)} message${total === 1 ? "" : "s"}.`
              : "Nothing new since the last check.",
        );
        await load();
        if (!out.more) break;
      }
    } catch {
      setNote(
        total
          ? `Read ${formatNumber(total)} message${total === 1 ? "" : "s"}, then stopped. The rest follows automatically.`
          : "Could not check just now.",
      );
    }
    setBusy("");
  }, [load]);

  useEffect(() => {
    load();
    // The callback sends the owner back here with the outcome in the URL.
    // Read once, then strip it, so a refresh does not re-announce it.
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("mail");
    if (outcome) {
      setNote(
        {
          connected: "Mailbox connected. Reading your mail now.",
          failed: "That did not go through. Try connecting again.",
          expired: "That link had expired. Try connecting again.",
        }[outcome] || "",
      );
      // Strip the marker so a refresh does not re-announce it. The path is
      // kept, because on setup this component is living on /signup and
      // rewriting to "/" would throw the owner out of the flow.
      window.history.replaceState({}, "", window.location.pathname);
      // Connecting is the moment the owner wants to see something happen, so
      // pull straight away rather than waiting for the sweep.
      if (outcome === "connected") pull();
    }
  }, [load, pull]);

  const connect = async () => {
    setBusy("connect");
    try {
      const { url } = await api.mailboxConnect(dest);
      window.location.href = url;
    } catch {
      setNote("Could not start. Try again.");
      setBusy("");
    }
  };


  const disconnect = async (id) => {
    setBusy(id);
    await api.mailboxDisconnect(id).catch(() => {});
    setNote("Mailbox disconnected. What was already read stays in your books.");
    await load();
    setBusy("");
  };

  if (!state) return null;

  return (
    <div className="card">
      <h3>Connect your mailbox</h3>

      {!state.available ? (
        <p className="muted" style={{ marginBottom: 0 }}>
          {state.detail}
        </p>
      ) : (
        <>
          {/* Fixed copy rather than the server's `detail`, which varied by
              state and buried the one thing worth saying: it reads the
              history as well as keeping up. `detail` still carries the
              exceptions — a mailbox that stopped syncing needs saying. */}
          <p className="muted">
            Longbook connects with your mailbox, extracts past history as well
            as syncs to keep information updated all the time.
          </p>
          {state.accounts.some((a) => a.status === "revoked") && (
            <p className="muted">{state.detail}</p>
          )}

          {state.accounts.map((a) => (
            <div className="row" key={a.id}>
              <div>
                <div style={{ fontWeight: 600, wordBreak: "break-all" }}>{a.email}</div>
                <div className="muted">
                  {a.status === "revoked"
                    ? "Stopped syncing — connect again"
                    : a.last_checked_at
                      ? `Last checked ${new Date(a.last_checked_at).toLocaleString("en-IN", {
                          dateStyle: "medium",
                          timeStyle: "short",
                        })}`
                      : "Waiting for the first check"}
                </div>
              </div>
              <button
                onClick={() => disconnect(a.id)}
                disabled={busy === a.id}
              >
                {busy === a.id ? "…" : "Disconnect"}
              </button>
            </div>
          ))}

          <div className="actions" style={{ marginTop: 12 }}>
            <button className="primary" onClick={connect} disabled={busy === "connect"}>
              {busy === "connect"
                ? "Opening…"
                : state.accounts.length
                  ? "Connect another"
                  : "Connect a mailbox"}
            </button>
            {state.accounts.length > 0 && (
              <button onClick={pull} disabled={busy === "sync"}>
                {busy === "sync" ? "Checking…" : "Check now"}
              </button>
            )}
          </div>

          {note && (
            <p className="muted" style={{ marginBottom: 0 }}>
              {note}
            </p>
          )}

          <p className="muted" style={{ marginBottom: 0, marginTop: 12 }}>
            Longbook only reads your mail. It never sends anything from your
            account, and you can disconnect at any time.
          </p>
        </>
      )}
    </div>
  );
}

// Collapsed by default. It grows by a row every time anything is added, so
// within a week it is the longest thing on the screen and it sits underneath
// the controls somebody actually came here to use. It is a record to consult,
// not a thing to read — so it stays one tap away rather than always open.
