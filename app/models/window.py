"""Conversation windows — the unit of extraction.

A trade order is built across several messages ("Need 500m White" ... "Olive
only 250 ready" ... "Okay make Olive 250" ... "Total 1050 meters"). Asking a
model for a confident record from any one of those lines is asking it to
guess, which is why per-message extraction auto-committed 10% of a real chat:
the model was correctly reporting that it could not be sure.

A window is a run of messages in one thread with no long silence in it. It is
identified by `window_key`, which is derived from the thread and the anchor
message rather than allocated, so re-running segmentation over a growing chat
keeps pointing at the same row instead of making a new one.

`content_hash` is what makes re-extraction cheap and idempotent: it covers the
member messages, so a window only re-runs when its contents actually changed.
"""

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TenantScoped


class ExtractionWindow(Base, TenantScoped):
    __tablename__ = "extraction_window"

    thread_key = Column(String(200), index=True)

    # Stable across re-segmentation: tenant + thread + anchor timestamp.
    window_key = Column(String(64), nullable=False)

    # The first message in the window. Deliberately not a foreign key:
    # `interaction.window_id` already points the other way, and declaring both
    # makes the two tables mutually dependent, which SQLAlchemy cannot order.
    anchor_interaction_id = Column(UUID(as_uuid=True))

    started_at = Column(DateTime, index=True)
    ended_at = Column(DateTime)
    message_count = Column(Integer, default=0)

    # Hash of the member messages as they stand now.
    content_hash = Column(String(64), nullable=False)
    # Hash as of the last successful extraction. Equal means up to date; this
    # is the progress watermark, moved here from the interaction.
    extracted_hash = Column(String(64), nullable=True)

    outcome = Column(String(24), default="pending", index=True)
    # pending | extracted | failed | curated
    # `curated` means a human has accepted or corrected something from this
    # window, so re-extraction must not overwrite their work.
    last_error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_extraction_window_tenant", "tenant_id"),
        UniqueConstraint("tenant_id", "window_key", name="uq_extraction_window_key"),
    )
