#!/usr/bin/env bash
# One-time provisioning of the Google Cloud stack. Idempotent: every step
# checks for what it creates, so a failed run can be repeated.
#
#   PROJECT=my-project REGION=asia-south1 ./deploy/provision.sh
#
# asia-south1 (Mumbai) is the default region deliberately — the customers are
# in Surat and Ahmedabad, and the dashboard is used on market wifi.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
INSTANCE="${INSTANCE:-textile-ops-db}"
DB_NAME="${DB_NAME:-textileops}"
DB_USER="${DB_USER:-textileops}"
BUCKET="${BUCKET:-${PROJECT}-textile-media}"
BQ_DATASET="${BQ_DATASET:-textile_ops}"
SA="textile-ops@${PROJECT}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT" >/dev/null

echo "==> APIs"
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com

echo "==> Artifact Registry"
gcloud artifacts repositories describe textile-ops --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create textile-ops \
    --repository-format=docker --location="$REGION" \
    --description="Textile Ops images"

echo "==> Service account"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create textile-ops --display-name="Textile Ops runtime"

# run.developer lets the API launch the backfill job; iam.serviceAccountUser
# lets it pass this same identity to that execution. Without both, the API
# quietly falls back to running backfills in its own process — which is the
# fragility the job exists to remove.
for role in roles/cloudsql.client roles/secretmanager.secretAccessor \
            roles/storage.objectAdmin roles/bigquery.dataEditor \
            roles/run.developer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${SA}" --role="$role" --condition=None >/dev/null
done

echo "==> Cloud SQL"
# db-g1-small (1.7GB) rather than the smaller db-f1-micro: 0.6GB is below
# what Postgres 16 wants when a backfill runs while the dashboard is in
# use, and an OOM mid-backfill is expensive to diagnose.
#
# --edition=ENTERPRISE is not optional. New projects default to
# ENTERPRISE_PLUS, which rejects every shared-core tier and only accepts
# db-perf-optimized-N-*, whose floor costs several times what this workload
# needs. Without this flag the create call fails outright.
gcloud sql instances describe "$INSTANCE" >/dev/null 2>&1 || \
  gcloud sql instances create "$INSTANCE" \
    --database-version=POSTGRES_16 --edition=ENTERPRISE --tier=db-g1-small \
    --region="$REGION" \
    --storage-auto-increase --backup --backup-start-time=19:00

gcloud sql databases describe "$DB_NAME" --instance="$INSTANCE" >/dev/null 2>&1 || \
  gcloud sql databases create "$DB_NAME" --instance="$INSTANCE"

if ! gcloud sql users list --instance="$INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
  DB_PASS="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  gcloud sql users create "$DB_USER" --instance="$INSTANCE" --password="$DB_PASS"
  printf '%s' "$DB_PASS" | gcloud secrets create db-password --data-file=- 2>/dev/null || \
    printf '%s' "$DB_PASS" | gcloud secrets versions add db-password --data-file=-
  echo "    database password stored in Secret Manager as db-password"
fi

echo "==> Bucket"
gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
    --uniform-bucket-level-access

echo "==> BigQuery"
bq --location="$REGION" show --dataset "${PROJECT}:${BQ_DATASET}" >/dev/null 2>&1 || \
  bq --location="$REGION" mk --dataset \
    --description="Agent run telemetry" "${PROJECT}:${BQ_DATASET}"

echo "==> Secrets"
# Created empty; fill them before the first deploy. Values never live in git,
# in the image, or in a Cloud Run env var.
# SMTP credentials are secrets like any other: the digest is the only thing
# that leaves the system, and it authenticates as the owner's own mail user.
for name in gemini-api-key admin-token scheduler-token \
            smtp-host smtp-user smtp-password digest-from signup-code; do
  gcloud secrets describe "$name" >/dev/null 2>&1 || \
    gcloud secrets create "$name" --replication-policy=automatic
done

cat <<EOF

Provisioned. Before the first deploy, set the secret values:

  printf '%s' "\$GEMINI_KEY" | gcloud secrets versions add gemini-api-key --data-file=-
  python -c 'import secrets; print(secrets.token_urlsafe(32))' | tr -d '\\n' \\
    | gcloud secrets versions add admin-token --data-file=-
  python -c 'import secrets; print(secrets.token_urlsafe(32))' | tr -d '\\n' \\
    | gcloud secrets versions add scheduler-token --data-file=-

Then: PROJECT=$PROJECT REGION=$REGION ./deploy/deploy.sh
EOF
