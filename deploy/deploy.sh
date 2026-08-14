#!/usr/bin/env bash
# Build and deploy: migrate, then API, then frontend, then the digest schedule.
# Order matters — the frontend bakes in the API URL, so the API must exist
# first, and the API must not serve a schema its database has not migrated to.
#
#   PROJECT=my-project REGION=asia-south1 ./deploy/deploy.sh
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
INSTANCE="${INSTANCE:-textile-ops-db}"
DB_NAME="${DB_NAME:-textileops}"
DB_USER="${DB_USER:-textileops}"
BUCKET="${BUCKET:-${PROJECT}-textile-media}"
BQ_DATASET="${BQ_DATASET:-textile_ops}"
SA="textile-ops@${PROJECT}.iam.gserviceaccount.com"
CONN="${PROJECT}:${REGION}:${INSTANCE}"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/textile-ops"
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo manual)"

gcloud config set project "$PROJECT" >/dev/null

# The unix-socket form: Cloud Run mounts the Cloud SQL socket at
# /cloudsql/<connection>, so there is no IP to allowlist and no proxy to run.
DB_PASS="$(gcloud secrets versions access latest --secret=db-password)"
DB_URL="postgresql+psycopg://${DB_USER}:${DB_PASS}@/${DB_NAME}?host=/cloudsql/${CONN}"

echo "==> Build API image"
gcloud builds submit --tag "${REPO}/api:${TAG}" .

echo "==> Migrate"
# A Cloud Run job, not a container-start hook: two instances starting at once
# would race on alembic, and a failed migration must fail the deploy loudly
# rather than crash-loop a serving revision.
if ! gcloud run jobs describe textile-migrate --region="$REGION" >/dev/null 2>&1; then
  CMD=create
else
  CMD=update
fi
gcloud run jobs $CMD textile-migrate \
  --image="${REPO}/api:${TAG}" \
  --region="$REGION" \
  --service-account="$SA" \
  --set-cloudsql-instances="$CONN" \
  --set-env-vars="DATABASE_URL=${DB_URL}" \
  --command=alembic --args=upgrade,head \
  --max-retries=0 --task-timeout=10m

gcloud run jobs execute textile-migrate --region="$REGION" --wait

echo "==> Backfill job"
# The backfill lives here rather than in the API process. A Cloud Run service
# container is replaced on every deploy and whenever the platform feels like
# it; a job execution is not, so a ten-minute backfill survives a deploy that
# lands in the middle of it. Retries are safe because extraction is keyed on
# each window's content hash — a finished window costs no model call.
if gcloud run jobs describe textile-backfill --region="$REGION" >/dev/null 2>&1; then
  BF=update
else
  BF=create
fi
gcloud run jobs $BF textile-backfill \
  --image="${REPO}/api:${TAG}" \
  --region="$REGION" \
  --service-account="$SA" \
  --set-cloudsql-instances="$CONN" \
  --set-env-vars="ENV=prod,GCS_BUCKET=${BUCKET},BQ_DATASET=${BQ_DATASET},DATABASE_URL=${DB_URL}" \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest" \
  --command=python --args=-m,scripts.backfill_job \
  --cpu=1 --memory=1Gi \
  --max-retries=2 --task-timeout=3600s

echo "==> Deploy API"
# min-instances=1 because a cold start pays for the SQLAlchemy engine and the
# Google SDK import on the owner's first tap of the morning, and this is a
# phone app used in a market.
#
# --no-cpu-throttling is load-bearing, not a tuning knob. Ingest returns 202
# immediately and runs the backfill as a background task; with Cloud Run's
# default throttling the container gets essentially no CPU once the response
# is sent, so the backfill stops partway through and never resumes. It looks
# exactly like a hang: the job row stays open, no error is logged, and the
# record count simply stops moving.
gcloud run deploy textile-api \
  --image="${REPO}/api:${TAG}" \
  --region="$REGION" \
  --service-account="$SA" \
  --allow-unauthenticated \
  --min-instances=1 --max-instances=10 \
  --cpu=1 --memory=1Gi --timeout=900 --no-cpu-throttling \
  --set-cloudsql-instances="$CONN" \
  --set-env-vars="ENV=prod,GCS_BUCKET=${BUCKET},BQ_DATASET=${BQ_DATASET},DATABASE_URL=${DB_URL},SMTP_PORT=587,SMTP_STARTTLS=true,BACKFILL_MODE=cloudrun,GCP_PROJECT=${PROJECT},GCP_REGION=${REGION}" \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,ADMIN_TOKEN=admin-token:latest,SCHEDULER_TOKEN=scheduler-token:latest,SMTP_HOST=smtp-host:latest,SMTP_USER=smtp-user:latest,SMTP_PASSWORD=smtp-password:latest,DIGEST_FROM=digest-from:latest,SIGNUP_CODE=signup-code:latest,INBOUND_ADDRESS=inbound-address:latest,INBOUND_PASSWORD=inbound-password:latest"

API_URL="$(gcloud run services describe textile-api --region="$REGION" --format='value(status.url)')"
echo "    API at $API_URL"

echo "==> Build and deploy frontend"
# --tag and --config are mutually exclusive, so the image name goes through as
# a substitution too.
gcloud builds submit frontend \
  --config=deploy/cloudbuild.frontend.yaml \
  --substitutions="_API=${API_URL},_IMAGE=${REPO}/web:${TAG}"

gcloud run deploy textile-web \
  --image="${REPO}/web:${TAG}" \
  --region="$REGION" \
  --allow-unauthenticated \
  --min-instances=1 --max-instances=5 \
  --cpu=1 --memory=512Mi

WEB_URL="$(gcloud run services describe textile-web --region="$REGION" --format='value(status.url)')"
echo "    Dashboard at $WEB_URL"

echo "==> Point the API's CORS and digest links at the deployed dashboard"
# Firebase Hosting fronts the same Cloud Run service, so the browser's Origin
# is longbook.co (or the .web.app URL) — not the run.app one. Every origin the
# app is served from has to be listed or its API calls fail CORS.
#
# DASHBOARD_URL is switchable because it goes into emails, and must not point
# at the custom domain until that domain actually resolves. CORS_ORIGINS is
# NOT switchable: the real domains belong in it always. Deriving the list from
# PUBLIC_URL once dropped the apex silently and every call from longbook.co
# 400'd, which looks like a browser problem and is not one.
#
# The ^|^ prefix switches gcloud's delimiter to | so the commas inside
# CORS_ORIGINS are not read as separate env vars.
PUBLIC_URL="${PUBLIC_URL:-https://longbook.co}"
gcloud run services update textile-api --region="$REGION" \
  --update-env-vars="^|^DASHBOARD_URL=${PUBLIC_URL}|CORS_ORIGINS=https://longbook.co,https://www.longbook.co,https://textile-ops-prod.web.app,https://textile-ops-prod.firebaseapp.com,${WEB_URL},http://localhost:3000"

echo "==> Digest schedule"
# 19:00 IST — after the market closes, before the owner sits down with the
# day's book. Cross-tenant, so it authenticates with the scheduler token.
SCHED_TOKEN="$(gcloud secrets versions access latest --secret=scheduler-token)"
# `create` and `update` disagree on the header flag: create takes --headers,
# update takes --update-headers and errors out on the other. Getting this
# wrong only shows up on the second deploy, which is the worst time to find it.
if gcloud scheduler jobs describe textile-digest --location="$REGION" >/dev/null 2>&1; then
  VERB=update
  HEADER_FLAG=--update-headers
else
  VERB=create
  HEADER_FLAG=--headers
fi
gcloud scheduler jobs $VERB http textile-digest \
  --location="$REGION" \
  --schedule="0 19 * * *" \
  --time-zone="Asia/Kolkata" \
  --uri="${API_URL}/api/jobs/digest" \
  --http-method=POST \
  "$HEADER_FLAG=X-Scheduler-Token=${SCHED_TOKEN}" \
  --attempt-deadline=900s

echo "==> Inbound mail schedule"
# Every ten minutes. Forwarded invoices should show up while the owner is
# still at the desk, without hammering IMAP.
if gcloud scheduler jobs describe textile-inbound --location="$REGION" >/dev/null 2>&1; then
  IVERB=update
  IHEADER=--update-headers
else
  IVERB=create
  IHEADER=--headers
fi
gcloud scheduler jobs $IVERB http textile-inbound   --location="$REGION"   --schedule="*/10 * * * *"   --time-zone="Asia/Kolkata"   --uri="${API_URL}/api/connect/inbound/poll"   --http-method=POST   "$IHEADER=X-Scheduler-Token=${SCHED_TOKEN}"   --attempt-deadline=300s

echo
echo "Deployed $TAG."
echo "  API       $API_URL"
echo "  Dashboard $WEB_URL"
