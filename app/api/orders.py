"""Order routes: the list, filters, and one order with its source conversation.

The detail endpoint answers "why does it say this?" in one call — the lines,
the party, the extraction that produced it and the messages it was drawn from.
Owners check these against Tally, and when they disagree this is what settles
it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import TenantDB, TenantId
from app.models.catalog import Quality
from app.models.ingestion import Extraction, Interaction
from app.models.orders import Dispatch, Order, OrderLine
from app.models.party import Party
from app.schemas.parties import OrderDetail, OrderLineOut, OrderPage, OrderRow

router = APIRouter()


@router.get("", response_model=OrderPage)
@router.get("/", response_model=OrderPage, include_in_schema=False)
def list_orders(
    tid: TenantId,
    db: TenantDB,
    status: str | None = Query(None, description="draft | confirmed | dispatched | closed"),
    party_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> OrderPage:
    where = [Order.tenant_id == tid]
    if status:
        where.append(Order.status == status)
    if party_id:
        where.append(Order.party_id == party_id)

    total = db.execute(select(func.count()).select_from(Order).where(*where)).scalar_one()

    by_status = dict(
        db.execute(
            select(Order.status, func.count())
            .where(Order.tenant_id == tid)
            .group_by(Order.status)
        ).all()
    )

    rows = db.execute(
        select(Order, Party.name)
        .outerjoin(Party, Party.id == Order.party_id)
        .where(*where)
        .order_by(Order.order_date.desc().nullslast(), Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return OrderPage(
        orders=[
            OrderRow(
                id=str(order.id),
                order_no=order.order_no,
                status=order.status,
                order_date=order.order_date,
                promised_date=order.promised_date,
                lines=len(order.lines),
                party_name=party_name,
                pending_fields=(order.attributes or {}).get("pending_fields", []),
            )
            for order, party_name in rows
        ],
        total=total,
        by_status={k or "unknown": v for k, v in by_status.items()},
    )


@router.get("/{order_id}", response_model=OrderDetail)
def order_detail(order_id: uuid.UUID, tid: TenantId, db: TenantDB) -> OrderDetail:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, "Order not found.")

    party = db.get(Party, order.party_id) if order.party_id else None

    lines = db.execute(
        select(OrderLine, Quality.code)
        .outerjoin(Quality, Quality.id == OrderLine.quality_id)
        .where(OrderLine.order_id == order_id)
    ).all()

    value = sum(
        float(line.quantity or 0) * float(line.rate or 0) for line, _ in lines
    )

    # The receipt: which extraction produced this, and what it was reading.
    extraction = db.execute(
        select(Extraction).where(
            Extraction.tenant_id == tid,
            Extraction.committed_type == "order",
            Extraction.committed_id == order_id,
        )
    ).scalars().first()

    conversation = []
    if extraction and extraction.window_id:
        cited = {str(i) for i in (extraction.source_message_ids or [])}
        messages = db.execute(
            select(Interaction)
            .where(Interaction.window_id == extraction.window_id)
            .order_by(Interaction.occurred_at.asc().nullslast(), Interaction.id.asc())
        ).scalars().all()
        conversation = [
            {
                "id": str(m.id),
                "sender": m.sender,
                "occurred_at": m.occurred_at.isoformat() if m.occurred_at else None,
                "body": m.body,
                "cited": str(m.id) in cited,
            }
            for m in messages
        ]

    dispatches = db.execute(
        select(Dispatch).where(Dispatch.tenant_id == tid, Dispatch.order_id == order_id)
        .order_by(Dispatch.dispatched_on.desc().nullslast())
    ).scalars().all()

    # What happened to this order, newest first — the owner reads it as a
    # story, not as a status column.
    timeline = []
    for d in dispatches:
        if d.delivered_on:
            timeline.append({"when": d.delivered_on.isoformat(),
                             "what": "Delivered"})
        if d.dispatched_on:
            timeline.append({
                "when": d.dispatched_on.isoformat(),
                "what": "Dispatched" + (f" via {d.transporter}" if d.transporter else ""),
            })
    if order.order_date:
        timeline.append({"when": order.order_date.isoformat(), "what": "Order recorded"})
    timeline.sort(key=lambda t: t["when"], reverse=True)

    return OrderDetail(
        id=order.id,
        order_no=order.order_no,
        status=order.status,
        order_date=order.order_date,
        promised_date=order.promised_date,
        notes=order.notes,
        party_id=order.party_id,
        party_name=party.name if party else None,
        lines=[
            OrderLineOut(
                quality=code or line.raw_description,
                quantity=float(line.quantity) if line.quantity is not None else None,
                unit=line.unit,
                rate=float(line.rate) if line.rate is not None else None,
            )
            for line, code in lines
        ],
        value=round(value, 2),
        pending_fields=(order.attributes or {}).get("pending_fields", []),
        dispatched=bool(dispatches),
        timeline=timeline,
        dispatch=(
            {
                "challan_no": dispatches[0].challan_no,
                "transporter": dispatches[0].transporter,
                "lr_no": dispatches[0].lr_no,
            }
            if dispatches
            else None
        ),
        extraction_id=extraction.id if extraction else None,
        trace_id=extraction.trace_id if extraction else None,
        conversation=conversation,
    )
