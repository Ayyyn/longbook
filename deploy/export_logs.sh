#!/usr/bin/env bash
# Pull the agent-run evidence CSVs off the deployed database onto this machine.
#
#   PROJECT=my-project ./deploy/export_logs.sh [--tenant <uuid>] [--days 30]
#   PROJECT=my-project ./deploy/export_logs.sh --full   # includes customer text
#
# Redacted by default. The redacted CSVs are the ones safe to hand to judges:
# same rows, minus business name, rationale and error text.
#
# The files are the XPRIZE submission evidence, so they have to land somewhere
# a person can attach them — not in an ephemeral container filesystem. This
# runs the exporter locally through the Cloud SQL Auth Proxy.
#
# Needs cloud-sql-proxy on PATH:
#   https://cloud.google.com/sql/docs/postgres/sql-proxy
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
INSTANCE="${INSTANCE:-textile-ops-db}"
DB_NAME="${DB_NAME:-textileops}"
DB_USER="${DB_USER:-textileops}"
PORT="${PORT:-5433}"          # not 5432: the local docker-compose db lives there
OUT="${OUT:-var/export}"

DB_PASS="$(gcloud secrets versions access latest --secret=db-password --project="$PROJECT")"

cloud-sql-proxy "${PROJECT}:${REGION}:${INSTANCE}" --port "$PORT" &
PROXY=$!
trap 'kill $PROXY 2>/dev/null || true' EXIT

# Give the proxy its listening socket before the exporter connects.
for _ in $(seq 1 30); do
  (echo >"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null && break
  sleep 1
done

DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASS}@127.0.0.1:${PORT}/${DB_NAME}" \
  python -m scripts.export_logs --out "$OUT" "$@"

echo "Wrote to $OUT"
