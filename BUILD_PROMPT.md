# Build brief — Textile Ops

You are completing a partially-built product. The architecture is decided. Do not
redesign it. Read `README.md` and the existing code first, then fill the gaps.

## What this is

An AI operations layer for Indian textile businesses — fabric wholesalers/traders
and B2C garment retailers. The owner works in a web dashboard. WhatsApp is an
**ingestion channel** (chat exports, voice notes, photos), never the interface.

Live target: paying customers using this within 6 days. Every decision should
favour "working on a trader's real data on Thursday" over completeness.

## Hard constraints — violate none of these

1. **No autonomous outbound messaging, ever.** The system drafts follow-up
   messages; the owner reviews and sends them via a `wa.me` link from their own
   number. Do not add WhatsApp Business API sending, do not add auto-reply, do not
   add scheduled sends. This is a product decision, not a limitation to route around.
2. **Profile-driven, never forked.** `BusinessProfile.modules` / `.vocabulary` /
   `.rules` decide behaviour. Wholesaler vs retail is data, not an if-branch on a
   segment string scattered through the codebase. Read the profile.
3. **`Agent.execute()` is the only way to run an agent.** It writes the `agent_run`
   row. Never call `Agent.run()` directly. Never write an agent that skips logging.
4. **Confidence gates all writes.** Extractions below `AUTO_COMMIT_FLOOR` (0.85) go
   to the review queue. Only `app/services/commit.py` writes business records.
5. **Tenant isolation on every query.** Every business table has `tenant_id`.
   No query may omit it. Add a session-level guard if that helps enforce it.
6. **Ledger maths is deterministic.** No model calls inside `app/services/ledger.py`.
   Owners will check these numbers against Tally; they must be reproducible.

## What exists

- `app/models/` — complete. Do not restructure. Add columns only via Alembic.
- `app/agents/` — all seven agents written with their prompts. Contracts are final.
- `app/pipeline.py` — LangGraph graph: extract → resolve → triage → apply.
- `app/ingestion/whatsapp_export.py` — parser, tested, handles iOS + Android formats.
- `app/llm.py` — Gemini wrapper, the single choke point for model calls.
- `app/profiles/*.yaml` — seed profiles the Configurator starts from.
- `evals/` — harness plus a 5-case golden set.

## What to build, in this order

### 1. Foundation (do first, nothing works without it)
- `app/db.py` — SQLAlchemy engine + session factory + a `tenant_session()` helper.
- Alembic init and the first migration from the existing models.
- Enable `pg_trgm` in the migration (`CREATE EXTENSION IF NOT EXISTS pg_trgm;`).
- `app/services/matching.py` — implement `exact_alias_match`, `phone_match`,
  `shortlist_parties` (trigram similarity, return objects with `.id` and `.score`).

### 2. The core loop (this is the product)
- `app/services/commit.py`:
  - `commit_record` — map extraction fields onto Order/OrderLine/Payment/Dispatch
    per `record_type`. Create the `Quality` if the code is new and confidence is
    high; otherwise flag for review.
  - `queue_for_review` — persist an `Extraction` with `status='needs_review'`.
  - `accept_correction` — commit the corrected record AND append the
    (input, corrected_output) pair to `BusinessProfile.examples`. Cap at 40,
    keep the most recent. This is how per-tenant accuracy compounds.
- `app/api/ingest.py` — upload endpoint for a WhatsApp export (.txt/.zip),
  Excel, or images. Parse, persist `Interaction` rows, enqueue pipeline runs.
  Must handle a 90-day export (several thousand messages) without timing out —
  return a job id and process in background.
- `app/api/review.py` — list queue, accept, correct, reject.

### 3. Onboarding
- `app/api/tenants.py` — create tenant, run the interview, invoke `Configurator`,
  persist `BusinessProfile`, then kick off backfill over the uploaded export.
- The onboarding flow must be completable in under 10 minutes with the owner
  present. That is a sales-meeting constraint, not a nice-to-have.

### 4. Ledger and digest
- `app/services/ledger.py` — implement all three functions. Ageing buckets use
  the profile's `overdue_days`. `overdue_crossings` must be diff-based (crossed
  *since the last run*), so store a watermark.
- `app/api/ledger.py` — party ledger, outstanding summary, ageing.
- Scheduled job: run `LedgerAnalyst` then `DigestComposer` at close of business
  (tenant-local time), email the digest with a dashboard deep link.

### 5. Frontend — Next.js PWA, mobile-first
Assume a 360px screen held in one hand in a crowded market. Five screens only:
- **Today** — the digest: money in, newly overdue, orders, low stock.
- **Review queue** — the accept/correct flow. Make this fast: one thumb, big
  targets, keyboard-free where possible. This screen is used daily.
- **Parties** — list, ledger, outstanding, "draft a reminder" button.
- **Orders** — list, filter by status, detail.
- **Agent Activity** — live feed of agent decisions with confidence, rationale,
  and human overrides. This is both a trust-builder and the demo footage.

English / Hindi / Gujarati toggle driven by `Tenant.locale`. Indian digit grouping
for all currency (₹1,25,000 not ₹125,000).

### 6. Connectors
- Excel/Sheets import: upload → agent maps columns to schema → preview → commit.
- Tally: **batch only.** Import parties and outstanding from Tally's XML/Excel
  export; emit voucher-ready XML the accountant imports. Do not attempt a live
  connection — TallyPrime's gateway is local to the customer's machine and a
  Windows sync agent is out of scope.

## Observability — not optional

`agent_run` rows must carry `trace_id`, model, prompt version, confidence,
latency, token counts, cost, outcome, and `human_override`. Stream to BigQuery
async. Add `scripts/export_logs.py` producing a CSV of agent runs and API usage —
this is submission evidence for the XPRIZE entry and must work on Aug 15.

## Testing

- Extend `evals/golden_set.jsonl` to 50+ cases from real messages before tuning
  any prompt. Wire `evals/run_eval.py` to actually call `Extractor`.
- Run the eval on every prompt change and print a before/after diff.
- Unit tests for the WhatsApp parser edge cases and the ledger maths.

## Style

- Python 3.12, type hints, `ruff` clean.
- No new dependencies beyond `requirements.txt` without saying why.
- Comments explain *why*, not *what*. The existing files show the register.
- Small commits, each one leaving the app runnable.

## Out of scope — do not build

GST filing, e-invoicing, POS/billing, inventory valuation, payroll, a native
mobile app, multi-currency, or any autonomous customer messaging.
