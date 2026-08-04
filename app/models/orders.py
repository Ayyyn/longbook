"""Orders, order lines, and dispatch.

Order lifecycle: draft -> confirmed -> partially_dispatched -> dispatched -> closed
An order created from a WhatsApp message starts as `draft` with a confidence
score and only becomes `confirmed` once the owner accepts it in the review queue.
"""

from sqlalchemy import Column, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, SourceTracked, TenantScoped


class Order(Base, TenantScoped, SourceTracked):
    __tablename__ = "order"

    party_id = Column(UUID(as_uuid=True), ForeignKey("party.id"), index=True)
    order_no = Column(String(64))
    status = Column(String(32), default="draft", index=True)
    order_date = Column(Date)
    promised_date = Column(Date)
    notes = Column(Text)

    lines = relationship("OrderLine", back_populates="order", cascade="all, delete")


class OrderLine(Base, TenantScoped):
    __tablename__ = "order_line"

    order_id = Column(UUID(as_uuid=True), ForeignKey("order.id", ondelete="CASCADE"))
    quality_id = Column(UUID(as_uuid=True), ForeignKey("quality.id"), nullable=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lot.id"), nullable=True)

    # Kept as free text too, because extraction often gets a code we can't map yet.
    raw_description = Column(String(300))
    quantity = Column(Numeric(14, 3))
    unit = Column(String(16), default="meter")
    rate = Column(Numeric(12, 2))

    order = relationship("Order", back_populates="lines")


class Dispatch(Base, TenantScoped, SourceTracked):
    __tablename__ = "dispatch"

    order_id = Column(UUID(as_uuid=True), ForeignKey("order.id"), index=True)
    challan_no = Column(String(64))
    transporter = Column(String(160))
    lr_no = Column(String(64))
    dispatched_on = Column(Date)
    delivered_on = Column(Date, nullable=True)
