"""Where the backfill runs.

The backfill is the slow half of onboarding — a model call per conversation
window, ten minutes for a few hundred messages. Running it as a FastAPI
background task means it lives and dies with the API container, and on Cloud
Run containers are replaced routinely: every deploy, every scale-down, every
crash. When that happens mid-run the work simply stops. Nothing raises,
nothing is logged, and the owner is left watching a progress bar that will
never move again — during their first ten minutes with the product.

So in production the API does not run the backfill at all. It asks Cloud Run
to execute a job, which has its own lifecycle and its own retries, and returns.

Re-running is always safe: extraction is keyed on each window's content hash,
so a window already done is skipped without a model call. That is what makes
both the job's retries and the manual resume endpoint harmless.
"""

from __future__ import annotations

import logging
import uuid

from app.config import settings

log = logging.getLogger(__name__)

_RUN_API = "https://run.googleapis.com/v2"


def _execute_cloud_run_job(tenant_id: uuid.UUID, job_id: uuid.UUID) -> None:
    """Ask Cloud Run to run one backfill, with the ids passed as env overrides.

    Imported lazily: a dev machine has no metadata server and no credentials,
    and importing google.auth at module scope would make that a startup cost
    for everyone.
    """
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    cfg = settings()
    project = cfg.gcp_project
    if not project:
        _, project = google.auth.default()
    if not project:
        raise RuntimeError("backfill_mode=cloudrun but no GCP project is configured.")

    name = (
        f"projects/{project}/locations/{cfg.gcp_region}/jobs/{cfg.backfill_job_name}"
    )
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = AuthorizedSession(credentials)
    response = session.post(
        f"{_RUN_API}/{name}:run",
        json={
            "overrides": {
                "containerOverrides": [
                    {
                        "env": [
                            {"name": "BACKFILL_TENANT_ID", "value": str(tenant_id)},
                            {"name": "BACKFILL_JOB_ID", "value": str(job_id)},
                        ]
                    }
                ]
            }
        },
        timeout=30,
    )
    response.raise_for_status()


def dispatch_backfill(tenant_id: uuid.UUID, job_id: uuid.UUID, background) -> str:
    """Start a backfill and say how it was started.

    Falls back to the in-process task if the job cannot be launched. A backfill
    that runs in the wrong place is recoverable; an upload that silently
    extracts nothing is not.
    """
    if settings().backfill_mode == "cloudrun":
        try:
            _execute_cloud_run_job(tenant_id, job_id)
            return "cloudrun"
        except Exception:  # noqa: BLE001 - degraded, never fatal to the upload
            log.exception("Could not execute the backfill job; running in-process.")

    from app.services.backfill import run_backfill

    background.add_task(run_backfill, tenant_id, job_id)
    return "inline"
