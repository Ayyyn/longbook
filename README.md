# Textile Ops — skeleton

AI operations layer for Indian textile businesses. Site-primary; WhatsApp is an
ingestion channel, not the interface.

## Shape

    ingest (WhatsApp export / Excel / Tally XML / photos / voice)
      -> Extractor -> Resolver -> Triage
      -> commit  OR  review queue (owner accepts/corrects)
      -> ledger, digest, drafts

## Non-negotiables baked into the design

1. **No autonomous outbound messaging.** Drafts only; owner sends via wa.me
   link from their own number. Removes WhatsApp Business API approval from the
   critical path and removes the worst trust failure mode.
2. **Profile-driven, not forked.** `BusinessProfile` (written by the
   Configurator agent) decides active modules, vocabulary, and thresholds.
   Wholesaler vs retail is a profile, not a branch.
3. **Every agent decision is logged.** `agent_run` is written by
   `Agent.execute`, not by callers. Debugging surface and submission evidence.
4. **Confidence gates writes.** Below `AUTO_COMMIT_FLOOR`, records go to the
   review queue. Corrections are harvested as per-tenant few-shot examples.

## Run

    docker compose up -d
    cp .env.example .env    # set GEMINI_API_KEY
    pip install -r requirements.txt
    uvicorn app.main:app --reload

## Status

Models, agent contracts, pipeline graph, WhatsApp parser, and eval harness are
written. `app/services/*` and `app/api/*` are stubs with explicit contracts —
these are the handoff surface for the build agent.
