"use client";

import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Chart from "./Chart";

// What the model writes, rendered properly.
//
// The first version of this was a hand-rolled parser that understood bullets
// and bold. That is fine until the model answers with a table, or a numbered
// list, or a heading — all of which it does, and all of which then arrived as
// literal pipes and hashes. Guessing which subset of markdown a model will
// use is a losing game, so this renders the whole of it.
//
// react-markdown builds React elements rather than setting innerHTML, so
// model output cannot inject markup. Raw HTML in the answer is not enabled.
//
// Charts are a fenced block the model emits:
//
//     ```chart
//     bar: Outstanding by party
//     Mahalaxmi Dyeing = 12500
//     Arihant Garments = 8000
//     ```
//
// One row per line rather than JSON, and that is a deliberate retreat. Asked
// for a JSON spec the model reliably wrote the wrapper and then left the array
// out — `{"type":"bar","title":"...","data":}` — because it was emitting the
// shape before it had worked out the numbers. A line format has nothing to
// nest and nothing to leave unclosed: the worst case is one unreadable row,
// not an unparseable block.
export default function AnswerBody({ text }) {
  const body = (text || "").trim();
  if (!body) return null;

  return (
    <div className="answer-body">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children }) {
            const spec = /language-chart/.test(className || "");
            if (spec) {
              return <Chart spec={parseChart(String(children))} />;
            }
            return <code className="answer-code">{children}</code>;
          },
          // Tables scroll rather than squashing the page on a phone.
          table({ children }) {
            return (
              <div className="answer-table-wrap">
                <table>{children}</table>
              </div>
            );
          },
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {body}
      </Markdown>
    </div>
  );
}

// `label = value` per line, with an optional "type: title" first line.
function parseChart(raw) {
  const lines = String(raw)
    .trim()
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  let type = "bar";
  let title = null;
  const data = [];

  for (const line of lines) {
    const header = line.match(/^(bar|share|pie|line)\s*:\s*(.*)$/i);
    if (header && !data.length) {
      type = header[1].toLowerCase();
      title = header[2].trim() || null;
      continue;
    }
    const row = line.match(/^(.+?)\s*=\s*(-?[\d.,]+)\s*$/);
    if (row) {
      const value = Number(row[2].replace(/,/g, ""));
      if (Number.isFinite(value)) data.push({ label: row[1].trim(), value });
    }
  }
  return { type, title, data };
}
