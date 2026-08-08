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

echo "==> Deploy API"
# min-instances=1 because a cold start pays for the SQLAlchemy engine and the
# Google SDK import on the owner's first tap of the morning, and this is a
# phone app used in a market.
gcloud run deploy textile-api \
  --image="${REPO}/api:${TAG}" \
  --region="$REGION" \
  --service-account="$SA" \
  --allow-unauthenticated \
  --min-instances=1 --max-instances=10 \
  --cpu=1 --memory=1Gi --timeout=900 \
  --set-cloudsql-instances="$CONN" \
  --set-env-vars="ENV=prod,GCS_BUCKET=${BUCKET},BQ_DATASET=${BQ_DATASET},DATABASE_URL=${DB_URL},SMTP_PORT=587,SMTP_STARTTLS=true" \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,ADMIN_TOKEN=admin-token:latest,SCHEDULER_TOKEN=scheduler-token:latest,SMTP_HOST=smtp-host:latest,SMTP_USER=smtp-user:latest,SMTP_PASSWORD=smtp-password:latest,DIGEST_FROM=digest-from:latest"

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
gcloud run services update textile-api --region="$REGION" \
  --update-env-vars="DASHBOARD_URL=${WEB_URL},CORS_ORIGINS=${WEB_URL}"

echo "==> Digest schedule"
# 19:00 IST — after the market closes, before the owner sits down with the
# day's book. Cross-tenant, so it authenticates with the scheduler token.
SCHED_TOKEN="$(gcloud secrets versions access latest --secret=scheduler-token)"
if gcloud scheduler jobs describe textile-digest --location="$REGION" >/dev/null 2>&1; then
  VERB=update
else
  VERB=create
fi
gcloud scheduler jobs $VERB http textile-digest \
  --location="$REGION" \
  --schedule="0 19 * * *" \
  --time-zone="Asia/Kolkata" \
  --uri="${API_URL}/api/jobs/digest" \
  --http-method=POST \
  --headers="X-Scheduler-Token=${SCHED_TOKEN}" \
  --attempt-deadline=900s

echo
echo "Deployed $TAG."
echo "  API       $API_URL"
echo "  Dashboard $WEB_URL"
