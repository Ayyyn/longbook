"""Notes: the things that are not orders and not payments.

A working business generates a great deal that no schema wants. "Ashokbhai's
son is taking over from Diwali." "The Surat transporter is unreliable on
Fridays." "Keep 200m of the navy aside for the Mehta reorder." None of that is
a party field or an order line, and until now the only place it could go was
the owner's memory — which is precisely what this product exists to replace.

So: a plain note, with the things that make one usable in a shop — a photo of
a sample or a hand-written chit, and a voice note for when typing on a phone
in a market is not realistic.

Deliberately unstructured. The temptation is to extract from these too, turn
them into records, tie them to parties. That is how a notes feature becomes a
worse version of the review queue. A note is the owner's own words, kept as
they wrote them, and searchable — nothing reads it and decides something.
"""

from __future__ import annotations

from sqlalchemy import Column, String, Text

from app.models.base import Base, TenantScoped


class Note(Base, TenantScoped):
    __tablename__ = "note"

    # The note itself. For a voice note this is the transcript the owner
    # corrected, not the raw one — what they meant to say is what is kept.
    body = Column(Text)

    # An attached photo, with the owner's own caption. Both optional: a note
    # can be text alone, a photo alone, or both.
    media_uri = Column(String(500))
    media_kind = Column(String(24))  # image | audio
    media_mime = Column(String(80))
    caption = Column(String(300))

    # "typed" | "voice" | "photo" — kept because a transcript that reads oddly
    # is easier to forgive when you can see it was spoken.
    source = Column(String(16), default="typed")
