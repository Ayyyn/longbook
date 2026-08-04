# CLAUDE.md

Read `BUILD_PROMPT.md` before writing code. It contains the build order and the
non-negotiable constraints.

## Quick facts
- FastAPI + SQLAlchemy + LangGraph + Gemini, Postgres, deployed on Cloud Run.
- Multi-tenant. `tenant_id` on every business row. Never query without it.
- `BusinessProfile` (JSONB) drives modules, vocabulary, and thresholds.

## Rules that are easy to break by accident
- Call `Agent.execute()`, never `Agent.run()` — logging lives in `execute`.
- Only `app/services/commit.py` writes business records from extractions.
- No model calls in `app/services/ledger.py`.
- The system never sends a message to a customer. Drafts + `wa.me` links only.

## Commands
    docker compose up -d
    uvicorn app.main:app --reload
    python -m evals.run_eval --tenant <uuid>
    ruff check .
