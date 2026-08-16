"""Saved conversations.

The chat used to keep its history in the browser: a dozen turns, this device
only, gone when the tab closed. The reasoning recorded at the time was that a
table of chat history is "a liability with no benefit the owner can see" —
which is a defensible privacy position and a poor product one. An owner who
worked out on Tuesday which customers were slow to pay should be able to open
that on Thursday from a different phone, and asking the same question twice
because the answer evaporated is not privacy, it is amnesia.

Tenant-scoped like every other business row, so isolation is enforced in the
session layer rather than here, and deleted with the tenant by the same
cascade. The sources of each answer are kept alongside it: a saved answer
without its citations is a claim with the evidence torn off, which is the one
thing this product refuses to show.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base, TenantScoped


class Conversation(Base, TenantScoped):
    __tablename__ = "conversation"

    # Taken from the first question rather than generated: a title nobody had
    # to write is a title nobody has to read twice, and it costs no model call.
    title = Column(String(120))

    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base, TenantScoped):
    __tablename__ = "chat_message"

    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role = Column(String(16), nullable=False)  # you | answer
    text = Column(Text, nullable=False)

    # Only on answers.
    answered = Column(Boolean)
    sources = Column(JSONB, default=list, nullable=False)
    latency_ms = Column(Integer)
    cost_usd = Column(Float)

    conversation = relationship("Conversation", back_populates="messages")
