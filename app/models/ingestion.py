"""Raw inbound material and the structured candidates extracted from it.

Interaction  = the raw thing that arrived (a WhatsApp line, a voice note, a photo)
Extraction   = what an agent thinks it means, with a confidence and a status

Nothing is written to the business tables directly from extraction. Low
confidence goes to the review queue; the owner accepts or corrects it, and the
correction is harvested as a per-tenant few-shot example.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.base import Base, TenantScoped


class Interaction(Base, TenantScoped):
    __tablename__ = "interaction"

    channel = Column(String(24), default="whatsapp_export")  # whatsapp_export|upload|manual
    sender = Column(String(160))
    sender_phone = Column(String(20), index=True)
    occurred_at = Column(DateTime, index=True)

    body = Column(Text)                    # transcribed/OCR'd text lives here too
    media_uri = Column(String(400))        # gs://... for audio and images
    media_kind = Column(String(24))        # audio | image | document | none
    detected_lang = Column(String(16))     # hi | gu | mr | en | mixed

    thread_key = Column(String(200), index=True)   # chat/group identifier


class Extraction(Base, TenantScoped):
    __tablename__ = "extraction"

    interaction_id = Column(UUID(as_uuid=True), ForeignKey("interaction.id"), index=True)

    record_type = Column(String(32), index=True)   # order|payment|enquiry|dispatch|noise
    payload = Column(JSONB, default=dict)          # candidate fields, pre-resolution
    resolved = Column(JSONB, default=dict)         # after Resolver links entities

    confidence = Column(Numeric(4, 3))
    reason = Column(Text)                          # why the agent is unsure
    status = Column(String(24), default="pending", index=True)
    # pending | auto_committed | needs_review | accepted | corrected | rejected

    committed_type = Column(String(32), nullable=True)
    committed_id = Column(UUID(as_uuid=True), nullable=True)
