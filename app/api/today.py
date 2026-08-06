"""The Today screen's facts.

Plain aggregates over committed records — no model calls, so the numbers on the
owner's home screen are reproducible and cheap to refresh.

Two of the four headline facts in the brief, newly-overdue and low-stock, need
the ledger and stock maths from BUILD_PROMPT section 4. They are reported as
unavailable rather than as zero: a zero would read as "nobody owes you money",
which is a different and much worse statement than "not built yet".
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import Profile, TenantDB, TenantId
from app.models.finance import Payment
from app.models.ingestion import Extraction
from app.models.observability import AgentRun
from app.models.orders import Dispatch, Order
from app.models.party import Party
from app.schemas.today import (
    ExceptionCounts,
    MoneyIn,
    Overdue,
    OrdersToday,
    RecentPayment,
    TodayDigest,
)
from app.services import exceptions as exception_rules
from app.services.ledger import outstanding_by_party, payment_trend

router = APIRouter()

OPEN_STATUSES = ("draft", "confirmed", "partially_dispatched")
RECENT_LIMIT = 5


@router.get("", response_model=TodayDigest)
@router.get("/", response_model=TodayDigest, include_in_schema=False)
def today(tid: TenantId, db: TenantDB, profile: Profile) -> TodayDigest:
    # Server-local date. Tenant-local close of business arrives with the
    # scheduled digest in section 4, which is when the distinction starts to
    # matter — a job firing at the wrong hour, not a number that is wrong.
    today_date = date.today()
    week_ago = today_date - timedelta(days=6)

    def total(*where) -> float:
        amount = db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.tenant_id == tid, *where
            )
        ).scalar_one()
        return float(amount or 0)

    def count(model, *where) -> int:
        return db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tid, *where)
        ).scalar_one()

    rules = (profile.rules if profile else {}) or {}
    overdue_days = int(rules.get("overdue_days", 45))

    positions = outstanding_by_party(db, tid, today_date, overdue_days)
    overdue_rows = [row for row in positions if row["is_overdue"]]
    worst = overdue_rows[0] if overdue_rows else None

    deviations = exception_rules.rate_deviations(
        db, tid, float(rules.get("rate_deviation_pct", 20)), today_date
    )
    stalled = exception_rules.stalled_orders(db, tid, today_date)
    slowing = payment_trend(db, tid)

    recent = db.execute(
        select(Payment, Party.name)
        .outerjoin(Party, Party.id == Payment.party_id)
        .where(Payment.tenant_id == tid)
        .order_by(Payment.received_on.desc().nullslast(), Payment.created_at.desc())
        .limit(RECENT_LIMIT)
    ).all()

    return TodayDigest(
        date=today_date,
        money_in=MoneyIn(
            today=total(Payment.received_on == today_date),
            last_7_days=total(Payment.received_on >= week_ago),
            payments_today=count(Payment, Payment.received_on == today_date),
        ),
        orders=OrdersToday(
            new_today=count(Order, Order.order_date == today_date),
            new_last_7_days=count(Order, Order.order_date >= week_ago),
            open_total=count(Order, Order.status.in_(OPEN_STATUSES)),
            awaiting_confirmation=count(Order, Order.status == "draft"),
        ),
        overdue=Overdue(
            total=round(sum(row["outstanding"] for row in overdue_rows), 2),
            parties=len(overdue_rows),
            worst_party=worst["party_name"] if worst else None,
            worst_days=worst["days_overdue"] if worst else 0,
            overdue_days=overdue_days,
        ),
        exceptions=ExceptionCounts(
            rate_deviations=len(deviations),
            stalled_orders=len(stalled),
            slowing_payers=len(slowing),
            total=len(deviations) + len(stalled) + len(slowing),
            headline=_headline(deviations, stalled, slowing),
        ),
        dispatches_today=count(Dispatch, Dispatch.dispatched_on == today_date),
        needs_review=count(Extraction, Extraction.status == "needs_review"),
        agent_decisions_today=count(AgentRun, func.date(AgentRun.created_at) == today_date),
        recent_payments=[
            RecentPayment(
                id=payment.id,
                party_name=party_name,
                amount=float(payment.amount or 0),
                mode=payment.mode,
                received_on=payment.received_on,
            )
            for payment, party_name in recent
        ],
        # Low stock still needs the lots/stock maths; overdue is real now.
        unavailable=["low_stock"],
    )


def _headline(deviations: list, stalled: list, slowing: list) -> str | None:
    """One sentence, picked by what costs the most to ignore.

    Money already owed by someone who is slowing down beats a late delivery,
    which beats a price that looked odd — that is the order an owner would
    read them in anyway.
    """
    if slowing:
        worst = slowing[0]
        return (
            f"{worst['party_name']} is paying {worst['slower_by_days']:.0f} days "
            f"slower than before"
        )
    if stalled:
        worst = stalled[0]
        return (
            f"{worst['party_name'] or 'An order'} is waiting "
            f"{worst['late_by_days']} days past promise"
        )
    if deviations:
        worst = deviations[0]
        return (
            f"{worst['quality_code']} sold {abs(worst['deviation_pct']):.0f}% "
            f"{worst['direction']} the usual rate"
        )
    return None
