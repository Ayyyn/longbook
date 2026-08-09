"""Cloud Run job entrypoint for the backfill.

Reads the tenant and job from the environment because that is what Cloud Run
job overrides can set, and runs exactly one backfill to completion. The
container exists only for this, so nothing here needs to be re-entrant with a
web server.

    BACKFILL_TENANT_ID=<uuid> BACKFILL_JOB_ID=<uuid> python -m scripts.backfill_job

A non-zero exit tells Cloud Run the execution failed, which is what makes its
retries work. Re-running is safe: extraction is keyed on each window's content
hash, so windows already finished are skipped without a model call.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid

from app.services.backfill import job_status, run_backfill

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("backfill_job")


def main() -> int:
    tenant_raw = os.environ.get("BACKFILL_TENANT_ID")
    job_raw = os.environ.get("BACKFILL_JOB_ID")
    if not tenant_raw or not job_raw:
        log.error("BACKFILL_TENANT_ID and BACKFILL_JOB_ID must both be set.")
        return 2

    tenant_id = uuid.UUID(tenant_raw)
    job_id = uuid.UUID(job_raw)

    log.info("Backfill starting for tenant=%s job=%s", tenant_id, job_id)
    run_backfill(tenant_id, job_id)

    # Report what landed, so the execution's logs answer "did it work?" without
    # anyone having to open the database.
    from app.db import tenant_session

    with tenant_session(tenant_id) as db:
        status = job_status(db, tenant_id, job_id)
    log.info(
        "Backfill finished: %s/%s messages, %s committed, %s queued for review.",
        status["processed"], status["total"], status["committed"], status["needs_review"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
