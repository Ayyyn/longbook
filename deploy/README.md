# Deploying

Two Cloud Run services (`textile-api`, `textile-web`) against one Cloud SQL
Postgres instance, in `asia-south1` — the customers are in Gujarat and the
dashboard is used on market wifi.

## First time

```sh
export PROJECT=your-project REGION=asia-south1
./deploy/provision.sh
```

That creates the APIs, Artifact Registry repo, runtime service account, Cloud
SQL instance and database, the media bucket, the BigQuery dataset, and three
empty secrets. It is idempotent — rerun it after a failure.

Then fill the secrets. They never live in git, in an image, or in a Cloud Run
env var:

```sh
printf '%s' "$GEMINI_KEY" | gcloud secrets versions add gemini-api-key --data-file=-
python -c 'import secrets; print(secrets.token_urlsafe(32))' | tr -d '\n' \
  | gcloud secrets versions add admin-token --data-file=-
python -c 'import secrets; print(secrets.token_urlsafe(32))' | tr -d '\n' \
  | gcloud secrets versions add scheduler-token --data-file=-
```

## Every deploy

```sh
PROJECT=your-project REGION=asia-south1 ./deploy/deploy.sh
```

In order: build the API image, run migrations as a Cloud Run **job**, deploy
the API, build the frontend with the API URL compiled in, deploy the frontend,
point the API's `CORS_ORIGINS` and `DASHBOARD_URL` at it, and create or update
the 19:00 IST digest schedule.

Migrations run as a job rather than at container start because two instances
starting together would race on alembic, and a bad migration should fail the
deploy loudly instead of crash-looping a live revision.

## Decisions worth knowing

- **`--min-instances=1` on both services.** A cold start pays for the
  SQLAlchemy engine and the Google SDK import on the owner's first tap of the
  morning. This is a phone app used standing in a market.
- **One uvicorn worker per instance.** Concurrency comes from Cloud Run adding
  instances. The LLM pacer's rate limit is per-process, so extra workers would
  silently multiply it and earn 429s.
- **Unix socket to Cloud SQL** (`?host=/cloudsql/<connection>`) — no IP to
  allowlist, no proxy sidecar.
- **`NEXT_PUBLIC_API_BASE` is a build arg, not a runtime env var.** It reaches
  the browser, so it has to be compiled in; that is the only reason
  `cloudbuild.frontend.yaml` exists.
- **CORS is not `*` in production.** The tenant token sits in the dashboard's
  local storage, so a permissive origin list is exactly how it would leak.
  `deploy.sh` sets `CORS_ORIGINS` to the deployed dashboard URL.

## Onboarding a real tenant

```sh
API=$(gcloud run services describe textile-api --region=$REGION --format='value(status.url)')
ADMIN=$(gcloud secrets versions access latest --secret=admin-token)

curl -X POST "$API/api/tenants" -H "X-Admin-Token: $ADMIN" \
  -H 'Content-Type: application/json' \
  -d '{"business_name":"Ravi Fabrics","owner_phone":"+919...","city":"Surat"}'
```

Keep the returned tenant token — it is what the dashboard signs in with.
Then upload the WhatsApp export through the onboarding endpoint; the backfill
runs in the background and the dashboard is usable while it does.

## Submission evidence

The agent-run CSVs must come off the deployed database onto a machine you can
attach files from:

```sh
PROJECT=your-project ./deploy/export_logs.sh --days 30
```

Needs [`cloud-sql-proxy`](https://cloud.google.com/sql/docs/postgres/sql-proxy)
on PATH. Writes `agent_runs.csv`, `agent_daily.csv` and `api_usage.csv` to
`var/export`.

## Verifying a deploy

```sh
curl -s "$API/health"                     # {"ok":true}
curl -s -o /dev/null -w '%{http_code}\n' "$API/api/today"   # 401 — auth is on
```

Both images are known to build and run locally:

```sh
docker build -t textile-api:smoke .
docker build -t textile-web:smoke --build-arg NEXT_PUBLIC_API_BASE=https://api.example frontend
```
