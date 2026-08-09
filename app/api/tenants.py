"""Onboarding routes.

The whole flow is meant to finish in under ten minutes with the owner present,
so it is three calls and nothing blocking:

    POST /api/tenants            create the business, hand back its token
    POST /api/tenants/sample     upload the WhatsApp export (parsed, stored)
    POST /api/tenants/configure  answer six questions, Configurator writes the
                                 profile, backfill starts behind a job id

Tenant creation is the one endpoint with no tenant to authenticate as, so it is
gated on an admin token instead.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile
from sqlalchemy import func, select

from app.api.deps import TenantDB, TenantId
from app.api.ingest import save_upload
from app.config import settings
from app.db import admin_session
from app.models.ingestion import Extraction, Interaction
from app.models.party import Party
from app.models.tenant import BusinessProfile, Tenant
from app.schemas.tenants import (
    ConfigureResult,
    PartyImportResult,
    Interview,
    ProfileOut,
    SampleAccepted,
    TenantCreate,
    TenantCreated,
    TenantMe,
)
from app.services.auth import issue_token
from app.services.backfill import run_backfill
from app.services.intake import IntakeError, interactions_from_upload
from app.services.onboarding import build_profile
from app.services.party_import import (
    import_parties,
    parse_upload,
    seeds_from_messages,
)

router = APIRouter()

PREVIEW_LINES = 5


def require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    expected = settings().admin_token
    if not expected:
        # Unset is only survivable on a developer's machine. Refusing loudly
        # beats quietly leaving tenant creation open in production.
        if settings().env != "dev":
            raise HTTPException(503, "ADMIN_TOKEN is not configured on this deployment.")
        return
    if not x_admin_token or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(401, "Invalid admin token.")


@router.post("", response_model=TenantCreated, status_code=201,
             dependencies=[Depends(require_admin)])
@router.post("/", response_model=TenantCreated, status_code=201, include_in_schema=False,
             dependencies=[Depends(require_admin)])
def create_tenant(payload: TenantCreate) -> TenantCreated:
    """Create the business and mint its token. The token is shown once."""
    with admin_session() as db:
        existing = db.execute(
            select(Tenant.id).where(Tenant.owner_phone == payload.owner_phone)
        ).scalars().first()
        if existing:
            raise HTTPException(409, "A tenant already exists for that owner phone.")

        tenant = Tenant(
            business_name=payload.business_name,
            owner_name=payload.owner_name,
            owner_phone=payload.owner_phone,
            owner_email=payload.owner_email,
            city=payload.city,
            locale=payload.locale,
        )
        token = issue_token(tenant)
        db.add(tenant)
        db.flush()
        tenant_id = tenant.id

    return TenantCreated(tenant_id=tenant_id, business_name=payload.business_name, token=token)


@router.post("/sample", response_model=SampleAccepted, status_code=202)
def upload_sample(
    tid: TenantId,
    db: TenantDB,
    file: UploadFile = File(...),
) -> SampleAccepted:
    """Store the export. Deliberately no BusinessProfile requirement — this
    runs before there is one, and its content is what writes it."""
    job_id = uuid.uuid4()
    tmp_path = save_upload(file)
    try:
        intake = interactions_from_upload(tid, file.filename, tmp_path, job_id)
    except IntakeError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    db.add_all(intake.interactions)
    db.flush()

    preview = [i.body for i in intake.interactions if i.body][:PREVIEW_LINES]
    return SampleAccepted(
        job_id=job_id,
        interactions=len(intake.interactions),
        skipped=intake.skipped,
        kind=intake.kind,
        preview=preview,
        detail=(
            f"{len(intake.interactions)} messages read. "
            "Answer the interview to configure and start the backfill."
        ),
    )


@router.post("/parties", response_model=PartyImportResult, status_code=202)
def import_party_list(
    tid: TenantId,
    db: TenantDB,
    file: UploadFile = File(...),
) -> PartyImportResult:
    """Import the party list from Tally XML or an .xlsx customer list.

    Runs before /configure so the backfill has somebody to attribute records
    to. Without it the chat export is used instead, which is a worse list.
    """
    tmp_path = save_upload(file)
    try:
        source, seeds = parse_upload(file.filename, tmp_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not seeds:
        raise HTTPException(400, "No parties found in that file.")

    result = import_parties(db, tid, seeds, source)
    total = db.execute(
        select(func.count()).select_from(Party).where(Party.tenant_id == tid)
    ).scalar_one()

    return PartyImportResult(
        **result.as_dict(),
        parties_total=total,
        preview=[seed.name for seed in seeds[:PREVIEW_LINES]],
        detail=(
            f"{result.created} parties added, {result.merged} matched existing"
            + (
                f", {result.opening_invoices} opening balances totalling "
                f"{result.total_outstanding:,.0f}"
                if result.opening_invoices
                else ""
            )
            + "."
        ),
    )


@router.post("/configure", response_model=ConfigureResult)
def configure(
    interview: Interview,
    tid: TenantId,
    db: TenantDB,
    background: BackgroundTasks,
) -> ConfigureResult:
    """Run the Configurator, persist the profile, and start the backfill."""
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "Tenant not found.")

    trace_id = uuid.uuid4()
    built = build_profile(db, tid, interview.render(), interview.segments, trace_id)

    profile = db.execute(
        select(BusinessProfile).where(BusinessProfile.tenant_id == tid)
    ).scalars().first()

    if profile is None:
        profile = BusinessProfile(tenant_id=tid, examples=[])
        db.add(profile)
    else:
        # Re-running onboarding bumps the version rather than losing what the
        # previous profile decided — the owner can be walked through it twice.
        profile.version = str(int(profile.version or "1") + 1)

    profile.segments = built["segments"]
    profile.modules = built["modules"]
    profile.vocabulary = built["vocabulary"]
    profile.rules = built["rules"]

    if tenant.onboarded_at is None:
        tenant.onboarded_at = datetime.utcnow()

    # The Resolver cannot attribute anything without a party list, and an
    # unattributed record cannot auto-commit — an empty party table sends the
    # whole 90-day history to review, which is where onboarding dies.
    #
    # Chat senders top up whatever was imported rather than replacing it.
    # Source priority is per party, not per import: `import_parties` merges
    # into an existing row and never overwrites what Tally already said, so a
    # counterparty the accountant's ledger has never heard of still becomes
    # somebody the backfill can attribute records to.
    before = db.execute(
        select(func.count()).select_from(Party).where(Party.tenant_id == tid)
    ).scalar_one()

    seeded_from = None
    seeds = seeds_from_messages(db, tid, tenant.owner_phone)
    if seeds:
        added = import_parties(db, tid, seeds, "messages").created
        if added:
            seeded_from = "messages" if before == 0 else "messages (topped up import)"

    parties = db.execute(
        select(func.count()).select_from(Party).where(Party.tenant_id == tid)
    ).scalar_one()

    pending = db.execute(
        select(func.count())
        .select_from(Interaction)
        .where(
            Interaction.tenant_id == tid,
            Interaction.attributes["outcome"].astext.is_(None),
        )
    ).scalar_one()

    db.flush()
    version = profile.version or "1"
    db.commit()

    # Everything uploaded before the profile existed. The owner is sitting
    # here watching, so this returns immediately and the screen follows the
    # job — records land as windows finish rather than all at the end.
    backfill_job = uuid.uuid4()
    background.add_task(run_backfill, tid, backfill_job)

    return ConfigureResult(
        tenant_id=tid,
        profile=ProfileOut(
            segments=built["segments"],
            modules=built["modules"],
            vocabulary=built["vocabulary"],
            rules=built["rules"],
            version=version,
            source=built["source"],
            confidence=built["confidence"],
            rationale=built["rationale"],
            rule_notes=built.get("rule_notes", []),
        ),
        pending_interactions=pending,
        backfill_job_id=backfill_job,
        parties=parties,
        parties_seeded_from=seeded_from,
        detail=(
            f"Profile written from the {built['source']}; "
            f"{pending} messages queued against {parties} parties."
        ),
    )


@router.get("/me", response_model=TenantMe)
def me(tid: TenantId, db: TenantDB) -> TenantMe:
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "Tenant not found.")

    profile = db.execute(
        select(BusinessProfile).where(BusinessProfile.tenant_id == tid)
    ).scalars().first()

    def count(model, *where) -> int:
        return db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tid, *where)
        ).scalar_one()

    return TenantMe(
        tenant_id=tenant.id,
        business_name=tenant.business_name,
        owner_name=tenant.owner_name,
        owner_phone=tenant.owner_phone,
        city=tenant.city,
        locale=tenant.locale or "en",
        onboarded_at=tenant.onboarded_at,
        profile=(
            ProfileOut(
                segments=profile.segments or [],
                modules=profile.modules or {},
                vocabulary=profile.vocabulary or {},
                rules=profile.rules or {},
                version=profile.version or "1",
                source="stored",
            )
            if profile
            else None
        ),
        parties=count(Party),
        interactions=count(Interaction),
        needs_review=count(Extraction, Extraction.status == "needs_review"),
    )
