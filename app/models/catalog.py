"""Quality (design/article) and Lot (shade/dye lot).

Lot matters enormously for wholesalers: same quality from a different dye lot
is not interchangeable, and mixing lots in one order is a costly mistake.
Retail tenants have the `lots` module off and use size/colour instead.
"""

from sqlalchemy import Column, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, SourceTracked, TenantScoped


class Quality(Base, TenantScoped, SourceTracked):
    __tablename__ = "quality"

    code = Column(String(64), nullable=False, index=True)
    name = Column(String(200))
    composition = Column(String(120))       # "60 cotton 40 poly"
    width_inch = Column(Numeric(6, 2))
    default_unit = Column(String(16), default="meter")   # meter | thaan | kg | piece
    default_rate = Column(Numeric(12, 2))


class Lot(Base, TenantScoped, SourceTracked):
    __tablename__ = "lot"

    quality_id = Column(UUID(as_uuid=True), ForeignKey("quality.id"), index=True)
    lot_no = Column(String(64), nullable=False)
    shade = Column(String(64))
    received_on = Column(Date)
    quantity = Column(Numeric(14, 3), default=0)
    unit = Column(String(16), default="meter")
