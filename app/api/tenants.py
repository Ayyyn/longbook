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
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy import func, select

from app.api.deps import TenantDB, TenantId
from app.api.ingest import _spool_uploads, save_upload
from app.config import settings
from app.db import admin_session
from app.models.ingestion import Extraction, IngestSource, Interaction
from app.models.party import Party
from app.models.tenant import BusinessProfile, Tenant
from app.schemas.tenants import (
    InterviewQuestions,
    PaymentRecord,
    Question,
    PaymentRecorded,
    RecoveryAccepted,
    RecoveryConfirm,
    RecoveryRequest,
    TenantSummary,
    ConfigureResult,
    PartyImportResult,
    Interview,
    ProfileOut,
    SampleAccepted,
    TenantCreate,
    TenantCreated,
    TenantMe,
    BusinessAnswer,
    BusinessProfileView,
    BusinessUpdate,
)
from sqlalchemy.orm.attributes import flag_modified

from app.services.matching import normalize_phone, store_phone
from app.services.access import access_for
from app.services.vocabulary import labels as vocab_labels
from app.services.credentials import email_token
from app.services import recovery as recovery_service
from app.services.mailer import send_email
from app.services.auth import issue_token
from app.services.dispatch import dispatch_backfill
from app.services.intake import IntakeError
from app.services.uploads import parse_many
from app.agents.interviewer import UNIVERSAL, Interviewer
from app.services.onboarding import build_profile, sample_messages
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
    """Create the business and mint its token. The token is shown once.

    The admin path grants no access on its own — there is no invite code to
    read a plan from — so record a payment afterwards, or hand the owner the
    invite code for what they bought and let them sign up with it.
    """
    return _create(payload)


# What each invite code buys. The code is the plan: an owner pays, gets the
# code for what they paid for, and access follows from it. Nothing in the app
# asks them to choose, because the choice was already made and paid for.
PLANS = {
    "monthly": {"days": 31, "plan": "monthly", "label": "monthly"},
    "annual": {"days": 365, "plan": "annual_prepaid", "label": "yearly"},
}


def resolve_signup_code(code: str | None) -> str | None:
    """Which plan this code is for, or None if it is not one of ours.

    compare_digest on every candidate rather than a dict lookup: comparing a
    secret with == leaks its length and prefix to anyone timing the endpoint.
    """
    if not code:
        return None
    settings_now = settings()
    candidates = (
        ("monthly", settings_now.signup_code_monthly),
        ("annual", settings_now.signup_code_annual),
        # Legacy single code. Codes already handed out keep working.
        ("monthly", settings_now.signup_code),
    )
    for plan, expected in candidates:
        if expected and secrets.compare_digest(code, expected):
            return plan
    return None


def require_signup_code(x_signup_code: Annotated[str | None, Header()] = None) -> str:
    """Gate self-serve signup on an invite code, and say which plan it is for.

    Deliberately not the admin token: that one mints tenants for every
    business, so a customer must never hold it. A signup code creates exactly
    one business and nothing else, and is rotated by changing one secret.

    No codes configured means self-serve signup is closed, which is the safe
    default — an open endpoint that returns a working token is an open door.
    """
    settings_now = settings()
    if not any((settings_now.signup_code_monthly, settings_now.signup_code_annual,
                settings_now.signup_code)):
        raise HTTPException(503, "Self-serve signup is not open on this deployment.")

    plan = resolve_signup_code(x_signup_code)
    if plan is None:
        raise HTTPException(401, "That signup code is not valid.")
    return plan


@router.post("/invite/check", status_code=200,
             dependencies=[Depends(require_signup_code)])
def check_invite(plan: Annotated[str, Depends(require_signup_code)]) -> dict[str, Any]:
    """Is this invite code good? Nothing is created, nothing is stored.

    Exists so the code can be checked before an owner is asked for anything
    else. Being told the code is wrong after typing a business name, a phone
    number and an email is the kind of small insult that loses people at the
    door — and the code is the one field they cannot fix themselves.

    Rate limiting is the same as signup's: the code is a shared secret, so a
    checking endpoint is a guessing oracle. The 401 from require_signup_code
    is deliberately identical whether the code is wrong or absent.
    """
    return {"valid": True, "plan": plan, "label": PLANS[plan]["label"]}


@router.post("/signup", response_model=TenantCreated, status_code=201,
             dependencies=[Depends(require_signup_code)])
def signup(
    payload: TenantCreate,
    plan: Annotated[str, Depends(require_signup_code)],
) -> TenantCreated:
    """Owner-facing tenant creation, with access granted by the invite code."""
    with admin_session() as db:
        since = datetime.utcnow() - timedelta(hours=1)
        recent = db.execute(
            select(func.count()).select_from(Tenant).where(Tenant.created_at >= since)
        ).scalar_one()
    if recent >= settings().signup_max_per_hour:
        # A leaked code should cost a cleanup, not a bill.
        raise HTTPException(429, "Too many businesses created just now. Try again shortly.")
    return _create(payload, plan=plan)


def _create(payload: TenantCreate, plan: str | None = None) -> TenantCreated:
    with admin_session() as db:
        # Matched on the last ten digits, not on the string. Otherwise the
        # same owner signing up as "+91 98250 66554" and "9825066554" gets two
        # businesses and neither has all their data.
        last10 = normalize_phone(payload.owner_phone)
        existing = db.execute(
            select(Tenant.id).where(
                Tenant.owner_phone.like(f"%{last10}") if last10
                else Tenant.owner_phone == payload.owner_phone
            )
        ).scalars().first()
        if existing:
            raise HTTPException(409, "A tenant already exists for that owner phone.")

        tenant = Tenant(
            business_name=payload.business_name,
            owner_name=payload.owner_name,
            # Stored digits-only. See store_phone: a number kept in the
            # shape someone typed it is a number nothing can find.
            owner_phone=store_phone(payload.owner_phone) or payload.owner_phone,
            owner_email=payload.owner_email,
            city=payload.city,
            locale=payload.locale,
        )
        # Access comes from the invite code that was used. A business that has
        # paid for a month gets a month; there is no trial and no window during
        # which nobody has decided anything.
        if plan and plan in PLANS:
            terms = PLANS[plan]
            tenant.plan = terms["plan"]
            tenant.paid_until = datetime.utcnow() + timedelta(days=terms["days"])

        token = issue_token(tenant)
        db.add(tenant)
        db.flush()
        tenant_id = tenant.id

    sent, detail = email_token(
        to=payload.owner_email,
        business_name=payload.business_name,
        phone=payload.owner_phone,
        token=token,
        dashboard_url=settings().dashboard_url,
    )
    return TenantCreated(
        tenant_id=tenant_id,
        business_name=payload.business_name,
        token=token,
        owner_phone=payload.owner_phone,
        emailed_to=payload.owner_email if sent else None,
        detail=detail if sent else "Store this token now — it is not shown again.",
    )


@router.post("/sample", response_model=SampleAccepted, status_code=202)
def upload_sample(
    tid: TenantId,
    db: TenantDB,
    files: list[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),
) -> SampleAccepted:
    """Store one or more exports. Deliberately no BusinessProfile requirement —
    this runs before there is one, and its content is what writes it.

    Several files in one action because an owner's business is not in one
    chat: the mill, the two big buyers and the transporter are four exports,
    and asking for them one at a time is how people give up halfway."""
    # `file` is the shape this endpoint had when it took one export. Kept
    # working so anything scripted against it does not break silently.
    incoming = [*(files or []), *([file] if file else [])]
    if not incoming:
        raise HTTPException(400, "No files were sent.")

    job_id = uuid.uuid4()
    spooled = _spool_uploads(incoming)
    try:
        rows, estimate = parse_many(db, tid, spooled, job_id)
    except IntakeError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    finally:
        for _, path in spooled:
            path.unlink(missing_ok=True)

    readable = [f for f in estimate.files if not f.error]
    if not readable:
        bad = estimate.files[0] if estimate.files else None
        raise HTTPException(bad.status_code if bad else 400,
                            bad.error if bad else "No files were sent.")

    db.add_all(rows)
    for f in estimate.files:
        db.add(
            IngestSource(
                tenant_id=tid, kind="upload", label=f.filename, job_id=job_id,
                messages=f.messages, duplicates=f.duplicates, skipped=f.skipped,
                media=f.media, bytes=f.bytes,
                status="failed" if f.error else "done", detail=f.error,
            )
        )
    db.flush()

    preview = [i.body for i in rows if i.body][:PREVIEW_LINES]
    return SampleAccepted(
        job_id=job_id,
        interactions=len(rows),
        skipped=sum(f.skipped for f in estimate.files),
        kind=readable[0].kind if readable else "unknown",
        preview=preview,
        estimated_minutes=estimate.minutes,
        duplicates=estimate.duplicates,
        detail=(
            f"{len(rows)} messages read from {len(readable)} "
            f"{'file' if len(readable) == 1 else 'files'}. "
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
        source, seeds = parse_upload(file.filename, tmp_path, db=db, tenant_id=tid)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not seeds:
        raise HTTPException(400, "No parties found in that file.")

    result = import_parties(db, tid, seeds, source)

    # Recorded like every other upload. Without this the customer list was
    # genuinely read — parties were created from it — and then never appeared
    # under "Imported so far", so the only honest conclusion an owner could
    # draw was that their spreadsheet had been ignored.
    db.add(IngestSource(
        tenant_id=tid,
        kind="party_list",
        label=file.filename or f"{source} party list",
        messages=result.created + result.merged,
        duplicates=result.merged,
        skipped=result.skipped,
        media=0,
        bytes=0,
        status="done",
        detail=(f"{result.created} added, {result.merged} matched existing"
                + (f", {result.opening_invoices} opening balances"
                   if result.opening_invoices else "")),
    ))
    db.flush()

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

    # Keep what was actually said, so it can be shown back and corrected later.
    kept = dict(tenant.interview or {})
    kept["answers"] = {**(kept.get("answers") or {}), **(interview.answers or {})}
    kept["basics"] = {
        "segments": interview.segments,
        "what_you_sell": interview.what_you_sell,
        "units": interview.units,
        "tracks_lots": interview.tracks_lots,
        "gives_credit": interview.gives_credit,
        "credit_days": interview.credit_days,
        "notes": interview.notes,
    }
    kept["answered_at"] = datetime.utcnow().isoformat()
    tenant.interview = kept
    flag_modified(tenant, "interview")

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
    dispatch_backfill(tid, backfill_job, background)

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

    access = access_for(tenant)
    return TenantMe(
        tenant_id=tenant.id,
        business_name=tenant.business_name,
        owner_name=tenant.owner_name,
        owner_phone=tenant.owner_phone,
        owner_email=tenant.owner_email,
        access_status=access.status,
        days_remaining=access.days_remaining,
        paid_until=tenant.paid_until,
        plan=tenant.plan,
        labels=vocab_labels(profile),
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


@router.post("/{tenant_id}/payment", response_model=PaymentRecorded,
             dependencies=[Depends(require_admin)])
def record_payment(tenant_id: uuid.UUID, payload: PaymentRecord) -> PaymentRecorded:
    """Mark a tenant as paid until a date. Admin only.

    This is the whole of billing. Money is collected in person and recorded
    here afterwards, which is how this trade already works and keeps card
    details out of a system with no reason to hold them.

    Moving the date forward restores access immediately — nothing was deleted
    when it lapsed, so there is nothing to restore but the date itself.
    """
    with admin_session() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(404, "No such tenant.")

        tenant.paid_until = payload.paid_until
        if payload.plan:
            tenant.plan = payload.plan
        # A payment always reopens a tenant that was switched off by hand;
        # otherwise renewing would look like it had silently failed.
        tenant.is_active = True
        db.flush()

        access = access_for(tenant)
        return PaymentRecorded(
            tenant_id=tenant.id,
            business_name=tenant.business_name,
            plan=tenant.plan,
            paid_until=tenant.paid_until,
            access_status=access.status,
            days_remaining=access.days_remaining,
        )


@router.get("/lookup", response_model=list[TenantSummary],
            dependencies=[Depends(require_admin)])
def lookup_tenant(phone: str = Query(..., min_length=4)) -> list[TenantSummary]:
    """Find a business by phone. Admin only.

    Exists because the support call starts with a phone number, not a uuid:
    someone rings saying they cannot get in, and this is how you find them
    before re-issuing anything.

    Matched on the last ten digits, since the number they read out will not
    have the country code the database does.
    """
    digits = "".join(c for c in phone if c.isdigit())[-10:]
    if len(digits) < 4:
        raise HTTPException(400, "Give at least the last four digits of the number.")

    with admin_session() as db:
        rows = db.execute(
            select(Tenant).where(Tenant.owner_phone.like(f"%{digits}"))
        ).scalars().all()
        out = []
        for tenant in rows:
            access = access_for(tenant)
            out.append(
                TenantSummary(
                    tenant_id=tenant.id,
                    business_name=tenant.business_name,
                    owner_name=tenant.owner_name,
                    owner_phone=tenant.owner_phone,
                    owner_email=tenant.owner_email,
                    city=tenant.city,
                    access_status=access.status,
                    days_remaining=access.days_remaining,
                    paid_until=tenant.paid_until,
                )
            )
        return out


@router.post("/{tenant_id}/token", response_model=TenantCreated,
             dependencies=[Depends(require_admin)])
def reissue_token(tenant_id: uuid.UUID, email: bool = Query(True)) -> TenantCreated:
    """Mint a fresh token for a tenant. Admin only.

    The stored digest cannot be reversed, so a lost token can never be looked
    up — only replaced. This is the answer to the phone call that starts "I
    got a new phone and now I cannot get in".

    Issuing a new token immediately stops the old one working, which is also
    what makes this the revocation lever: if a token leaks, replace it.
    Nothing else about the business changes.
    """
    with admin_session() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(404, "No such tenant.")
        token = issue_token(tenant)
        db.flush()
        business_name, phone, to = tenant.business_name, tenant.owner_phone, tenant.owner_email

    sent, detail = (False, "Not emailed.")
    if email:
        sent, detail = email_token(
            to=to,
            business_name=business_name,
            phone=phone,
            token=token,
            dashboard_url=settings().dashboard_url,
        )

    return TenantCreated(
        tenant_id=tenant_id,
        business_name=business_name,
        token=token,
        owner_phone=phone,
        emailed_to=to if sent else None,
        detail=(
            f"{detail} The previous token has stopped working."
            if sent
            else "New token issued. The previous token has stopped working."
        ),
    )


@router.post("/recover", response_model=RecoveryAccepted)
def request_recovery(payload: RecoveryRequest) -> RecoveryAccepted:
    """Ask for a link that will issue a new token. Public.

    Nothing is rotated here. Rotation is destructive — it signs the owner's
    phone out — so it must require the mailbox, not just the number. All this
    does is post a signed, expiring link to the address already on file.

    The response never varies. Saying "no such business" would turn this into
    a way to test which phone numbers are customers.
    """
    digits = "".join(c for c in payload.phone if c.isdigit())[-10:]
    if len(digits) < 10:
        return RecoveryAccepted()

    with admin_session() as db:
        tenant = db.execute(
            select(Tenant).where(Tenant.owner_phone.like(f"%{digits}"))
        ).scalars().first()
        if tenant is None or not tenant.owner_email:
            return RecoveryAccepted()
        tenant_id, name, to = tenant.id, tenant.business_name, tenant.owner_email

    try:
        link = (
            f"{settings().dashboard_url.rstrip('/')}/recover"
            f"?t={recovery_service.sign(tenant_id)}"
        )
    except recovery_service.RecoveryError:
        return RecoveryAccepted()

    text, html = recovery_service.recovery_email(name, link)
    send_email(to, f"Getting back into Longbook — {name}", text, html)
    return RecoveryAccepted()


@router.post("/recover/confirm", response_model=TenantCreated)
def confirm_recovery(payload: RecoveryConfirm) -> TenantCreated:
    """Open the link: issue a new token and show it once. Public but signed."""
    try:
        tenant_id = recovery_service.verify(payload.token_payload)
    except recovery_service.RecoveryError as exc:
        raise HTTPException(400, str(exc)) from exc

    with admin_session() as db:
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(400, "This link is not valid.")
        token = issue_token(tenant)
        db.flush()
        name, phone, to = tenant.business_name, tenant.owner_phone, tenant.owner_email

    sent, _ = email_token(
        to=to, business_name=name, phone=phone, token=token,
        dashboard_url=settings().dashboard_url,
    )
    return TenantCreated(
        tenant_id=tenant_id,
        business_name=name,
        token=token,
        owner_phone=phone,
        emailed_to=to if sent else None,
        detail="New token issued. Your previous token has stopped working.",
    )


@router.get("/interview", response_model=InterviewQuestions)
def interview_questions(
    tid: TenantId, db: TenantDB, stage: str = Query("universal")
) -> InterviewQuestions:
    """The questions to ask this owner.

    `stage=universal` returns the three that are true of any business and can
    be asked before anything has been read. `stage=generated` reads the
    uploaded sample and writes the rest — which is why upload now comes first.
    """
    if stage != "generated":
        return InterviewQuestions(
            questions=[Question(**q) for q in UNIVERSAL],
            generated=False,
            observations=[],
        )

    messages = sample_messages(db, tid)
    decision = Interviewer(db, tid).execute({
        "messages": messages,
        "answers": {},
    })
    output = decision.output or {}
    questions = [Question(**q) for q in output.get("questions") or []]

    # Written down as soon as they are asked. Generating them costs a model
    # call and is not deterministic, so an owner who reloads the page would
    # otherwise be shown a different interview than the one they started.
    tenant = db.get(Tenant, tid)
    if tenant is not None and questions:
        kept = dict(tenant.interview or {})
        kept["questions"] = (
            [{**q, "stage": "universal"} for q in UNIVERSAL]
            + [{**q.model_dump(), "stage": "generated"} for q in questions]
        )
        kept["observations"] = output.get("observations") or []
        kept["asked_at"] = datetime.utcnow().isoformat()
        tenant.interview = kept
        flag_modified(tenant, "interview")

    return InterviewQuestions(
        questions=questions,
        generated=bool(output.get("generated")),
        observations=output.get("observations") or [],
    )


def _business_view(db, tid: uuid.UUID) -> BusinessProfileView:
    """Assemble the 'about the business' picture from whatever exists.

    Both halves are optional and independent: the interview may be answered
    with no profile written (onboarding abandoned), and in principle a profile
    may exist for a tenant onboarded before the interview was kept. Neither
    case may 404 — this screen is the one place an owner can see what we think
    their business is, and it has to work when things are half-finished.
    """
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "Tenant not found.")

    kept = tenant.interview or {}
    answers = kept.get("answers") or {}
    asked = kept.get("questions") or []

    rows: list[BusinessAnswer] = [
        BusinessAnswer(
            question=q.get("question", ""),
            answer=answers.get(q.get("question", "")),
            hint=q.get("hint"),
            stage=q.get("stage", "generated"),
        )
        for q in asked
        if q.get("question")
    ]
    # Answers to questions we no longer have a record of asking still belong to
    # the owner — losing them because the question list changed would be worse
    # than showing one without its hint.
    seen = {r.question for r in rows}
    rows.extend(
        BusinessAnswer(question=q, answer=a, stage="generated")
        for q, a in answers.items()
        if q not in seen
    )

    profile = db.execute(
        select(BusinessProfile).where(BusinessProfile.tenant_id == tid)
    ).scalars().first()

    return BusinessProfileView(
        business_name=tenant.business_name,
        configured=profile is not None,
        onboarded_at=tenant.onboarded_at,
        asked_at=kept.get("asked_at"),
        answered_at=kept.get("answered_at"),
        answers=rows,
        observations=kept.get("observations") or [],
        segments=(profile.segments if profile else []) or [],
        modules=(profile.modules if profile else {}) or {},
        vocabulary=(profile.vocabulary if profile else {}) or {},
        rules=(profile.rules if profile else {}) or {},
        version=profile.version if profile else None,
        basics=kept.get("basics") or {},
    )


@router.get("/business", response_model=BusinessProfileView)
def business(tid: TenantId, db: TenantDB) -> BusinessProfileView:
    """What we asked, what you told us, and what we made of it."""
    return _business_view(db, tid)


@router.put("/business", response_model=BusinessProfileView)
def update_business(
    payload: BusinessUpdate, tid: TenantId, db: TenantDB
) -> BusinessProfileView:
    """Correct the answers, and optionally rebuild the profile from them.

    Rebuilding is opt-in. The Configurator decides thresholds and which modules
    are on, so re-running it on every keystroke-level correction would quietly
    change how the whole system behaves because somebody fixed a spelling.
    """
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise HTTPException(404, "Tenant not found.")

    kept = dict(tenant.interview or {})
    if payload.answers:
        kept["answers"] = {**(kept.get("answers") or {}), **payload.answers}
    if payload.basics:
        kept["basics"] = {**(kept.get("basics") or {}), **payload.basics}
    kept["answered_at"] = datetime.utcnow().isoformat()
    tenant.interview = kept
    flag_modified(tenant, "interview")

    if payload.reconfigure:
        basics = kept.get("basics") or {}
        interview = Interview(
            segments=basics.get("segments") or [],
            what_you_sell=basics.get("what_you_sell"),
            units=basics.get("units"),
            tracks_lots=basics.get("tracks_lots"),
            gives_credit=basics.get("gives_credit"),
            credit_days=basics.get("credit_days"),
            notes=basics.get("notes"),
            answers=kept.get("answers") or {},
        )
        built = build_profile(
            db, tid, interview.render(), interview.segments, uuid.uuid4()
        )
        profile = db.execute(
            select(BusinessProfile).where(BusinessProfile.tenant_id == tid)
        ).scalars().first()
        if profile is None:
            profile = BusinessProfile(tenant_id=tid, examples=[])
            db.add(profile)
        else:
            profile.version = str(int(profile.version or "1") + 1)
        profile.segments = built["segments"]
        profile.modules = built["modules"]
        profile.vocabulary = built["vocabulary"]
        profile.rules = built["rules"]
        db.flush()

    return _business_view(db, tid)
