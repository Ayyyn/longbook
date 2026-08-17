"""Analytics endpoints.

A thin layer. Everything of substance is in app/services/analytics.py, and the
one thing worth repeating here is what does *not* happen: no endpoint below
asks a model for a number. The insights endpoint hands the model figures that
SQL has already produced and asks it for sentences. If that boundary ever
moves, the dashboard starts inventing, and a dashboard figure carries no
citation and no visible workings for anyone to catch it with.
"""

from __future__ import annotations


from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import TenantDB, TenantId
from app.models.tenant import Tenant
from app.services import analytics
from app.services.analytics import AnalyticsError

router = APIRouter()


def _schema(db, tid):
    tenant = db.get(Tenant, tid)
    return analytics.discover(db, business_name=tenant.business_name if tenant else "")


class SchemaOut(BaseModel):
    business_name: str
    first_record: str | None
    last_record: str | None
    days: int
    records: int
    measures: list[dict]
    dimensions: list[dict]


@router.get("/schema", response_model=SchemaOut)
def schema(tid: TenantId, db: TenantDB) -> SchemaOut:
    """What this business's data can support — the dashboard is built from
    this rather than from a fixed list of charts."""
    return SchemaOut(**_schema(db, tid).as_dict())


@router.get("/overview")
def overview(tid: TenantId, db: TenantDB,
             period: str = Query("30d"),
             party_kind: str | None = None,
             city: str | None = None) -> dict:
    """Everything the first screenful needs, in one call.

    One round trip rather than five: on a phone in a market, four extra
    requests is four extra chances to show a half-built screen.
    """
    sc = _schema(db, tid)
    filters = {"party_kind": party_kind, "city": city}
    start, end = analytics.window_for(period)

    if not sc.records:
        return {
            "schema": sc.as_dict(), "period": period,
            "start": start.isoformat(), "end": end.isoformat(),
            "kpis": [], "alerts": [], "rankings": {},
            "empty": "Nothing has been read into this business yet.",
        }

    try:
        return {
            "schema": sc.as_dict(),
            "period": period,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "kpis": analytics.kpis(db, sc, period, filters),
            "alerts": analytics.alerts(db, sc),
            "rankings": analytics.rankings(db, sc, period, filters),
            "empty": "",
        }
    except AnalyticsError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/series")
def series(tid: TenantId, db: TenantDB,
           metric: str = Query("received"),
           freq: str = Query("month"),
           period: str = Query("12m"),
           compare: bool = Query(False),
           party_kind: str | None = None,
           city: str | None = None) -> dict:
    """One measure over time, optionally against the period before it."""
    sc = _schema(db, tid)
    start, end = analytics.window_for(period)
    filters = {"party_kind": party_kind, "city": city}
    try:
        current = analytics.series(db, metric, freq, start, end, filters)
        out: dict = {"metric": metric, "freq": freq, "points": current,
                     "comparison": [], "no_comparison": ""}
        if compare:
            prev_start, prev_end = analytics.previous(start, end)
            if sc.first_record and prev_start < sc.first_record:
                out["no_comparison"] = (
                    "The previous period starts before your records do."
                )
            else:
                out["comparison"] = analytics.series(
                    db, metric, freq, prev_start, prev_end, filters)
        return out
    except AnalyticsError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/breakdown")
def breakdown(tid: TenantId, db: TenantDB,
              metric: str = Query("received"),
              dimension: str = Query("party"),
              period: str = Query("30d"),
              party_kind: str | None = None,
              city: str | None = None) -> dict:
    """Analyse by: a measure split across a dimension."""
    start, end = analytics.window_for(period)
    filters = {"party_kind": party_kind, "city": city}
    try:
        rows = analytics.breakdown(db, metric, dimension, start, end, filters)
    except AnalyticsError as exc:
        raise HTTPException(400, str(exc)) from exc

    # The chart type follows the shape of the answer rather than a setting:
    # three categories are a share, twelve are a ranking.
    chart = "share" if 0 < len(rows) <= 4 else "bar"
    return {"metric": metric, "dimension": dimension, "chart": chart, "rows": rows}


@router.get("/drill")
def drill(tid: TenantId, db: TenantDB,
          metric: str = Query(...), dimension: str = Query(...),
          value: str = Query(...), period: str = Query("30d")) -> dict:
    """The records behind one bar."""
    start, end = analytics.window_for(period)
    try:
        return {"rows": analytics.drill(db, metric, dimension, value, start, end)}
    except AnalyticsError as exc:
        raise HTTPException(400, str(exc)) from exc


class Insight(BaseModel):
    kind: str          # observation | driver | attention
    text: str


@router.get("/insights")
def insights(tid: TenantId, db: TenantDB, period: str = Query("30d")) -> dict:
    """Sentences about figures that have already been computed.

    The model is shown the aggregates and asked to say what stands out. It is
    told, in the prompt and again here, that it may not produce a number that
    is not in front of it and may not assert a cause. "Revenue fell because
    the festival season ended" is a story; "revenue fell 18%, and Mehta — who
    was a third of last month — placed nothing" is an observation with a
    pointer, which is what an owner can act on.
    """
    from app.config import settings
    from app.llm import generate_json

    sc = _schema(db, tid)
    if not sc.records:
        return {"insights": [], "detail": "Nothing has been read in yet."}

    filters: dict = {}
    facts = {
        "period": period,
        "history_days": sc.days,
        "kpis": analytics.kpis(db, sc, period, filters),
        "rankings": analytics.rankings(db, sc, period, filters),
        "alerts": analytics.alerts(db, sc),
    }

    system = (
        "You write two to four short observations for a small business owner, "
        "from figures that have already been calculated for you.\n\n"
        "RULES:\n"
        "1. Never state a number that is not in the data given to you. Do not "
        "add, multiply, or estimate. If you want to mention a figure, copy it.\n"
        "2. Never assert a cause. You may say what moved and what else moved "
        "with it; you may not say one caused the other. 'X fell, and Y — who "
        "was a third of last month — ordered nothing' is allowed. 'X fell "
        "because Y stopped ordering' is not.\n"
        "3. If a comparison was withheld, do not work around it.\n"
        "4. One sentence each, plain words, rupees in Indian digit grouping.\n"
        "5. Say nothing rather than pad. Two real observations beat four.\n\n"
        'Return JSON: {"insights": [{"kind": "observation|attention", '
        '"text": "..."}]}'
    )
    try:
        out, _usage = generate_json(
            model=settings().model_chat,
            system=system,
            user=str(facts),
        )
        rows = [i for i in (out.get("insights") or []) if i.get("text")][:4]
        return {"insights": rows, "detail": ""}
    except Exception:  # noqa: BLE001 - a dashboard must render without them
        return {"insights": [], "detail": "Insights could not be written just now."}
