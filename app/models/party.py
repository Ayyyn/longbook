"""Parties (customers/suppliers) and their name aliases.

Textile trade books the same customer as "Ashok Tex", "Ashok Textiles",
"ashok bhai" and "A.T. Mumbai". Alias resolution is a first-class concern,
not a string-similarity afterthought — the Resolver agent owns it.
"""

from sqlalchemy import Boolean, Column, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import ARRAY

from app.models.base import Base, SourceTracked, TenantScoped


class Party(Base, TenantScoped, SourceTracked):
    __tablename__ = "party"

    name = Column(String(200), nullable=False)
    aliases = Column(ARRAY(String), default=list)
    kind = Column(String(20), default="customer")  # customer | supplier | broker
    phone = Column(String(20), index=True)
    city = Column(String(80))
    gstin = Column(String(20))

    # Credit terms — the number the owner cares about most.
    credit_days = Column(Integer, default=0)
    credit_limit = Column(Numeric(14, 2), nullable=True)

    is_walk_in = Column(Boolean, default=False)  # retail segment
