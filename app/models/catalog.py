"""What a business sells, and the batches it arrives in.

These were called Quality and Lot, which are fabric-trade words. A machinery
dealer sells items with model numbers; a chemical distributor sells items with
grades; a garment retailer sells items with sizes and colours. The storage is
the same shape in every case, so the storage uses the neutral word.

What each business *calls* an item is display, and comes from
`BusinessProfile.vocabulary` — see `app/services/vocabulary.py`. A fabric
trader sees "Quality", a machinery dealer sees "Model". Nothing here decides
that.

`Batch` matters where goods are not interchangeable between runs: dye lots for
a fabric wholesaler, heat numbers for a steel stockist, manufacturing batches
for anything with an expiry. Tenants who do not track them have the module off.
"""

from sqlalchemy import Column, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, SourceTracked, TenantScoped


class Item(Base, TenantScoped, SourceTracked):
    __tablename__ = "item"

    code = Column(String(64), nullable=False, index=True)
    name = Column(String(200))
    # Free text, whatever describes the thing: "60 cotton 40 poly", "EN8
    # forged", "98% pure". Deliberately not parsed.
    composition = Column(String(120))
    width_inch = Column(Numeric(6, 2))
    # No default: the unit a business sells in comes from its profile, and
    # guessing "meter" here is how a machinery dealer ends up with metres of
    # bearings.
    default_unit = Column(String(16))
    default_rate = Column(Numeric(12, 2))


class Batch(Base, TenantScoped, SourceTracked):
    __tablename__ = "batch"

    item_id = Column(UUID(as_uuid=True), ForeignKey("item.id"), index=True)
    # Whatever the batch is identified by: lot number, heat number, roll.
    lot_no = Column(String(64), nullable=False)
    shade = Column(String(64))
    received_on = Column(Date)
    quantity = Column(Numeric(14, 3), default=0)
    unit = Column(String(16))
