"""Base model classes. Everything is tenant-scoped and carries a JSONB
`attributes` bag so profile-specific fields never need a migration."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TenantScoped(TimestampMixin):
    """Every business record hangs off a tenant. Row-level isolation is
    enforced in the session layer (see app/db.py), not by convention."""

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    @declared_attr
    def tenant_id(cls):
        return Column(
            UUID(as_uuid=True),
            ForeignKey("tenant.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )

    # Profile-driven fields land here rather than in new columns.
    attributes = Column(JSONB, default=dict, nullable=False)

    @declared_attr
    def __table_args__(cls):
        return (Index(f"ix_{cls.__tablename__}_tenant", "tenant_id"),)


class SourceTracked:
    """Where a record came from — needed for the audit trail and for
    letting the owner trace any number back to the original message."""

    source = Column(String(32), default="manual")  # manual|whatsapp|excel|tally|pdf
    source_ref = Column(String(256), nullable=True)  # interaction id, row no, voucher id
