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

## Sign-in, and what it is not

An owner signs in with their phone number and the access token issued when
their business was set up (`/onboarding` shows that token exactly once). The
token is stored in the browser's `localStorage`; the phone is checked against
the tenant the token belongs to, so a token pasted under the wrong number is
refused. A 401 anywhere clears both and returns to `/login`.

**Known limitations of this model.** It is deliberately the smallest thing
that lets a real owner use the product, and it should not survive contact with
a second cohort:

- **The token does not expire.** There is no session lifetime, no refresh and
  no server-side revocation list. A token is valid until the tenant is deleted.
- **Signing out clears only this browser.** A token that has leaked stays
  valid everywhere else it was pasted; the only remedy is issuing a new one.
- **`localStorage` is readable by any script on the origin.** That is why CORS
  is pinned to the dashboard's own URL in production rather than `*`, but it
  is mitigation, not a fix.
- **The phone check is a guard, not authentication.** It stops a token being
  used under the wrong number; it does not prove who is holding the phone.
- **No OTP.** Phone verification was deliberately not built.

Replacing this with phone OTP and short-lived sessions is the first thing to
do once the launch cohort is past.

## Status

Models, agent contracts, pipeline graph, WhatsApp parser, and eval harness are
written. `app/services/*` and `app/api/*` are stubs with explicit contracts —
these are the handoff surface for the build agent.
