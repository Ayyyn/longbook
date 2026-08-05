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

from app.api.deps import TenantDB, TenantId
from app.models.finance import Payment
from app.models.ingestion import Extraction
from app.models.observability import AgentRun
from app.models.orders import Dispatch, Order
from app.models.party import Party
from app.schemas.today import MoneyIn, OrdersToday, RecentPayment, TodayDigest

router = APIRouter()

OPEN_STATUSES = ("draft", "confirmed", "partially_dispatched")
RECENT_LIMIT = 5


@router.get("", response_model=TodayDigest)
@router.get("/", response_model=TodayDigest, include_in_schema=False)
def today(tid: TenantId, db: TenantDB) -> TodayDigest:
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
        unavailable=["newly_overdue", "low_stock"],
    )
