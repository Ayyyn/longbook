"""The close-of-business digest.

LedgerAnalyst computes (deterministically), DigestComposer writes it, the
mailer delivers it with a deep link back to the dashboard. In that order and
no other: the model never produces a number, it only phrases numbers it was
handed.

If the model is unavailable the digest still goes out, written by
`_plain_digest` below. A trader who gets a plainer email than usual is fine;
a trader who gets no email on the evening a customer crossed 45 days is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.agents import DigestComposer, LedgerAnalyst
from app.config import settings
from app.models.finance import Payment
from app.models.ingestion import Extraction
from app.models.orders import Order
from app.models.tenant import BusinessProfile, Tenant
from app.services import exceptions as exception_rules
from app.services.ledger import outstanding_by_party
from app.services.mailer import send_email

# Every tenant in the launch cohort trades in India. Tenant has no timezone
# column, and inventing one for a single-country launch would be pretending to
# a generality the product does not have yet.
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_DIGEST_HOUR = 19  # close of business, after the market winds down

TOP_N = 5


@dataclass
class DigestResult:
    tenant_id: uuid.UUID
    business_name: str
    as_of: date
    facts: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    emailed: bool = False
    detail: str = ""
    composed_by: str = "digest_composer"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": str(self.tenant_id),
            "business_name": self.business_name,
            "as_of": str(self.as_of),
            "headline": self.body.get("headline"),
            "emailed": self.emailed,
            "detail": self.detail,
            "composed_by": self.composed_by,
            "newly_overdue": len(self.facts.get("newly_overdue", [])),
            "exceptions": self.facts.get("exception_count", 0),
        }


def tenant_local_hour(as_of: datetime | None = None) -> int:
    return (as_of or datetime.now(timezone.utc)).astimezone(IST).hour


def dashboard_link(path: str = "/") -> str:
    return f"{settings().dashboard_url.rstrip('/')}{path}"


def gather_facts(db, tenant_id: uuid.UUID, profile, as_of: date) -> dict[str, Any]:
    """Everything the digest may mention. Computed, never generated."""
    rules = (profile.rules if profile else {}) or {}
    overdue_days = int(rules.get("overdue_days", 45))

    analyst = LedgerAnalyst(db, tenant_id, profile)
    ledger = analyst.execute({"as_of": as_of}, trace_id=uuid.uuid4()).output

    money_in = db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.tenant_id == tenant_id, Payment.received_on == as_of
        )
    ).scalar_one()

    def count(model, *where) -> int:
        return db.execute(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id, *where)
        ).scalar_one()

    deviations = exception_rules.rate_deviations(
        db, tenant_id, float(rules.get("rate_deviation_pct", 20)), as_of
    )
    stalled = exception_rules.stalled_orders(db, tenant_id, as_of)
    outstanding = outstanding_by_party(db, tenant_id, as_of, overdue_days)

    return {
        "as_of": str(as_of),
        "overdue_days": overdue_days,
        "money_in_today": float(money_in or 0),
        "payments_today": count(Payment, Payment.received_on == as_of),
        "orders_today": count(Order, Order.order_date == as_of),
        "orders_awaiting_confirmation": count(Order, Order.status == "draft"),
        "needs_review": count(Extraction, Extraction.status == "needs_review"),
        "ageing": ledger.get("ageing", {}),
        "newly_overdue": ledger.get("newly_overdue", []),
        "slowing_payers": ledger.get("risk_flags", []),
        "total_outstanding": round(sum(r["outstanding"] for r in outstanding), 2),
        "top_debtors": outstanding[:TOP_N],
        "rate_deviations": deviations[:TOP_N],
        "stalled_orders": stalled[:TOP_N],
        "exception_count": len(deviations) + len(stalled) + len(ledger.get("risk_flags", [])),
    }


def _rupees(amount: float) -> str:
    whole = f"{int(round(amount)):d}"
    if len(whole) <= 3:
        return f"Rs {whole}"
    head, tail = whole[:-3], whole[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return f"Rs {','.join(parts)},{tail}"


def _plain_digest(facts: dict[str, Any]) -> dict[str, Any]:
    """The fallback: same facts, no model."""
    sections = []

    money = [
        f"Received today: {_rupees(facts['money_in_today'])} "
        f"across {facts['payments_today']} payment(s)",
        f"Total outstanding: {_rupees(facts['total_outstanding'])}",
    ]
    for row in facts["newly_overdue"]:
        money.append(
            f"NEWLY OVERDUE: {row['party_name']} — {_rupees(row['outstanding'])}, "
            f"{row['days_overdue']} days"
        )
    sections.append({"title": "Money", "items": money})

    if facts["orders_today"] or facts["orders_awaiting_confirmation"]:
        sections.append({
            "title": "Orders",
            "items": [
                f"New orders today: {facts['orders_today']}",
                f"Awaiting your confirmation: {facts['orders_awaiting_confirmation']}",
            ],
        })

    flags = []
    for row in facts["stalled_orders"]:
        flags.append(
            f"{row['party_name'] or 'Order'} — {row['late_by_days']} days late ({row['reason']})"
        )
    for row in facts["rate_deviations"]:
        flags.append(
            f"{row['quality_code']} at {_rupees(row['rate'])} vs usual "
            f"{_rupees(row['usual_rate'])} ({row['deviation_pct']:+.0f}%)"
        )
    for row in facts["slowing_payers"]:
        flags.append(
            f"{row['party_name']} paying {row['slower_by_days']:.0f} days slower than before"
        )
    if flags:
        sections.append({"title": "Needs a look", "items": flags})

    headline = (
        f"{_rupees(facts['money_in_today'])} in today"
        + (f", {len(facts['newly_overdue'])} newly overdue" if facts["newly_overdue"] else "")
    )
    actions = []
    if facts["needs_review"]:
        actions.append(f"{facts['needs_review']} item(s) waiting in the review queue")
    for row in facts["newly_overdue"][:3]:
        actions.append(f"Chase {row['party_name']} for {_rupees(row['outstanding'])}")

    return {"headline": headline, "sections": sections, "action_items": actions}


def render_text(business: str, as_of: date, body: dict[str, Any]) -> str:
    lines = [f"{business} — {as_of:%d %b %Y}", "", body.get("headline", ""), ""]
    for section in body.get("sections", []):
        lines.append(section.get("title", "").upper())
        lines.extend(f"  - {item}" for item in section.get("items", []))
        lines.append("")
    actions = body.get("action_items") or []
    if actions:
        lines.append("TO DO")
        lines.extend(f"  - {item}" for item in actions)
        lines.append("")
    lines.append(f"Open the dashboard: {dashboard_link('/')}")
    lines.append(f"Review queue: {dashboard_link('/review')}")
    return "\n".join(lines)


def render_html(business: str, as_of: date, body: dict[str, Any]) -> str:
    def escape(value: Any) -> str:
        return (
            str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

    parts = [
        "<div style=\"font-family:system-ui,sans-serif;max-width:560px\">",
        f"<h2 style=\"margin:0\">{escape(business)}</h2>",
        f"<p style=\"color:#666;margin:2px 0 16px\">{as_of:%d %b %Y}</p>",
        f"<p style=\"font-size:18px;font-weight:600\">{escape(body.get('headline', ''))}</p>",
    ]
    for section in body.get("sections", []):
        parts.append(f"<h3 style=\"margin-bottom:4px\">{escape(section.get('title'))}</h3><ul>")
        parts.extend(f"<li>{escape(item)}</li>" for item in section.get("items", []))
        parts.append("</ul>")
    if body.get("action_items"):
        parts.append("<h3 style=\"margin-bottom:4px\">To do</h3><ul>")
        parts.extend(f"<li>{escape(item)}</li>" for item in body["action_items"])
        parts.append("</ul>")
    parts.append(
        f"<p><a href=\"{dashboard_link('/')}\" "
        "style=\"background:#0b6b3a;color:#fff;padding:10px 16px;border-radius:8px;"
        "text-decoration:none;display:inline-block\">Open dashboard</a></p>"
    )
    parts.append("</div>")
    return "".join(parts)


def run_digest_for_tenant(db, tenant: Tenant, as_of: date | None = None) -> DigestResult:
    """Compute, compose, and send one tenant's digest."""
    as_of = as_of or datetime.now(IST).date()
    profile = db.execute(
        select(BusinessProfile).where(BusinessProfile.tenant_id == tenant.id)
    ).scalars().first()

    facts = gather_facts(db, tenant.id, profile, as_of)

    composed_by = "digest_composer"
    try:
        composer = DigestComposer(db, tenant.id, profile)
        body = composer.execute(
            {"facts": facts, "locale": tenant.locale or "en"}, trace_id=uuid.uuid4()
        ).output
        if not body.get("sections") and not body.get("headline"):
            raise ValueError("composer returned nothing usable")
    except Exception:  # noqa: BLE001 - the digest must still go out
        body = _plain_digest(facts)
        composed_by = "fallback"

    text = render_text(tenant.business_name, as_of, body)
    html = render_html(tenant.business_name, as_of, body)
    subject = f"{tenant.business_name}: {body.get('headline') or 'today'}"

    emailed, detail = send_email(tenant.owner_email or "", subject, text, html)

    return DigestResult(
        tenant_id=tenant.id,
        business_name=tenant.business_name,
        as_of=as_of,
        facts=facts,
        body=body,
        text=text,
        emailed=emailed,
        detail=detail,
        composed_by=composed_by,
    )
