#!/usr/bin/env bash
# Frontend only. Use this for anything that touches frontend/ and nothing else.
#
#   Preview first (nobody sees it but you):
#     PROJECT=textile-ops-prod ./deploy/deploy-web.sh --preview
#
#   Then send it live:
#     PROJECT=textile-ops-prod ./deploy/deploy-web.sh --promote
#
#   Or straight to production in one step, if you are sure:
#     PROJECT=textile-ops-prod ./deploy/deploy-web.sh
#
# Why this exists separately from deploy.sh: that script rebuilds the API image,
# runs migrations and re-registers the schedulers — about eight minutes, and it
# touches the database. A CSS change should not do any of that.
#
# --preview deploys a Cloud Run revision that serves NO traffic, reachable only
# at its own tagged URL. Production keeps serving the previous revision while
# you look at it. This is the closest thing to a staging environment that costs
# nothing and cannot drift from production, because it *is* production, minus
# the traffic.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/textile-ops"
MODE="${1:-}"

gcloud config set project "$PROJECT" >/dev/null

# A tag that changes every build. Reusing one tag for different code — which is
# what happens when it comes from an unchanged git HEAD — means the registry
# overwrites the old image and you cannot roll back to it.
TAG="web-$(date +%Y%m%d-%H%M%S)"
if git rev-parse --short HEAD >/dev/null 2>&1; then
  DIRTY=""
  git diff --quiet || DIRTY="-dirty"
  TAG="${TAG}-$(git rev-parse --short HEAD)${DIRTY}"
fi

if [ "$MODE" = "--promote" ]; then
  echo "==> Sending the newest revision live"
  gcloud run services update-traffic textile-web --region="$REGION" --to-latest
  echo "    Live at https://longbook.co"
  exit 0
fi

API_URL="$(gcloud run services describe textile-api --region="$REGION" --format='value(status.url)')"
echo "==> Building frontend against ${API_URL}"
gcloud builds submit frontend \
  --config=deploy/cloudbuild.frontend.yaml \
  --substitutions="_API=${API_URL},_IMAGE=${REPO}/web:${TAG}"

if [ "$MODE" = "--preview" ]; then
  echo "==> Deploying as a preview revision (no traffic)"
  # min-instances=0 for a preview: it serves nobody most of the time, and a
  # warm instance parked on a revision you looked at once is a bill for
  # nothing. First load is a second slower; that is the right trade here.
  gcloud run deploy textile-web \
    --image="${REPO}/web:${TAG}" \
    --region="$REGION" \
    --allow-unauthenticated \
    --min-instances=0 --max-instances=2 \
    --cpu=1 --memory=512Mi \
    --no-traffic --tag=preview
  URL="$(gcloud run services describe textile-web --region="$REGION" \
        --format='value(status.traffic[].url)' | tr ';' '\n' | grep preview || true)"
  echo
  echo "    Preview: ${URL:-check: gcloud run services describe textile-web --region=$REGION}"
  echo "    Production is untouched and still on the previous revision."
  echo "    Happy with it?  PROJECT=$PROJECT ./deploy/deploy-web.sh --promote"
  exit 0
fi

echo "==> Deploying to production"
gcloud run deploy textile-web \
  --image="${REPO}/web:${TAG}" \
  --region="$REGION" \
  --allow-unauthenticated \
  --min-instances=1 --max-instances=5 \
  --cpu=1 --memory=512Mi

echo "    Live at https://longbook.co"
