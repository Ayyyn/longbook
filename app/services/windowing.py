"""Segmenting a chat into conversation windows.

Deterministic and re-runnable: the same messages always produce the same
windows with the same keys, so segmentation can be re-run over a growing chat
without orphaning what was already extracted.

Boundaries are a silence gap rather than anything cleverer. Traders return to
a topic after a break and start a fresh exchange; within a sitting, the
messages belong together. Two caps stop a busy day becoming one enormous
window: a message count, and a character budget standing in for tokens.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.models.ingestion import Interaction
from app.models.window import ExtractionWindow

# A window's text is sent to the model in full, so this is the real cost lever.
# ~4 chars per token, so 6000 chars is roughly 1500 tokens of conversation.
DEFAULT_GAP_MINUTES = 120
DEFAULT_MAX_MESSAGES = 40
DEFAULT_MAX_CHARS = 6000

NO_THREAD = "_"


@dataclass
class Segment:
    thread_key: str
    messages: list[Interaction] = field(default_factory=list)

    @property
    def anchor(self) -> Interaction:
        return self.messages[0]

    @property
    def started_at(self) -> datetime | None:
        return self.messages[0].occurred_at

    @property
    def ended_at(self) -> datetime | None:
        return self.messages[-1].occurred_at

    def window_key(self) -> str:
        """Stable across re-segmentation.

        Keyed on the anchor rather than the contents: a window that gains a
        later message keeps its identity, which is what lets re-extraction
        supersede instead of duplicate.
        """
        anchor = self.anchor
        stamp = anchor.occurred_at.isoformat() if anchor.occurred_at else str(anchor.id)
        raw = f"{self.thread_key}|{stamp}|{anchor.id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def content_hash(self) -> str:
        """Covers membership and text, so an edited or added message re-runs."""
        digest = hashlib.sha256()
        for message in self.messages:
            digest.update(str(message.id).encode())
            digest.update((message.body or "").encode())
            digest.update((message.media_uri or "").encode())
        return digest.hexdigest()[:64]

    def render(self) -> str:
        """The conversation as the model sees it.

        Each line is numbered so the model can cite which messages a record
        came from, and timestamped because "Friday" only means something
        relative to the message that said it.
        """
        lines = []
        for index, message in enumerate(self.messages, start=1):
            when = message.occurred_at.strftime("%d/%m %H:%M") if message.occurred_at else "?"
            who = message.sender or "unknown"
            body = (message.body or "").replace("\n", " / ")
            if message.media_kind and message.media_kind != "none":
                body = f"{body} [{message.media_kind} attached]".strip()
            lines.append(f"[{index}] {when} {who}: {body}")
        return "\n".join(lines)

    def id_for_index(self, index: Any) -> uuid.UUID | None:
        """Map a model-cited line number back to a real interaction id."""
        try:
            position = int(index)
        except (TypeError, ValueError):
            return None
        if 1 <= position <= len(self.messages):
            return self.messages[position - 1].id
        return None


def _rules(profile) -> tuple[int, int, int]:
    rules = (profile.rules if profile else {}) or {}
    return (
        int(rules.get("window_gap_minutes", settings().window_gap_minutes)),
        int(rules.get("window_max_messages", settings().window_max_messages)),
        int(rules.get("window_max_chars", settings().window_max_chars)),
    )


def segment(messages: list[Interaction], profile=None) -> list[Segment]:
    """Split one tenant's messages into windows, thread by thread."""
    gap_minutes, max_messages, max_chars = _rules(profile)
    gap = timedelta(minutes=gap_minutes)

    by_thread: dict[str, list[Interaction]] = {}
    for message in messages:
        by_thread.setdefault(message.thread_key or NO_THREAD, []).append(message)

    segments: list[Segment] = []
    for thread_key, thread_messages in by_thread.items():
        # Undated messages (an Excel row, a bare photo) sort last and each
        # stands alone — there is no conversation to place them in.
        dated = sorted(
            (m for m in thread_messages if m.occurred_at is not None),
            key=lambda m: (m.occurred_at, str(m.id)),
        )
        undated = [m for m in thread_messages if m.occurred_at is None]

        current: Segment | None = None
        size = 0
        for message in dated:
            body_len = len(message.body or "")
            too_long = current is not None and (
                len(current.messages) >= max_messages or size + body_len > max_chars
            )
            gapped = (
                current is not None
                and current.ended_at is not None
                and message.occurred_at - current.ended_at > gap
            )
            if current is None or gapped or too_long:
                current = Segment(thread_key=thread_key)
                segments.append(current)
                size = 0
            current.messages.append(message)
            size += body_len

        for message in undated:
            segments.append(Segment(thread_key=thread_key, messages=[message]))

    return segments


def sync_windows(db, tenant_id: uuid.UUID, profile=None) -> list[ExtractionWindow]:
    """Re-segment a tenant's messages and reconcile the window rows.

    Safe to call repeatedly: existing windows are updated in place by their
    stable key, and only the ones whose contents changed are left needing
    extraction.
    """
    messages = db.execute(
        select(Interaction).where(Interaction.tenant_id == tenant_id)
    ).scalars().all()
    if not messages:
        return []

    existing = {
        w.window_key: w
        for w in db.execute(
            select(ExtractionWindow).where(ExtractionWindow.tenant_id == tenant_id)
        ).scalars().all()
    }

    windows: list[ExtractionWindow] = []
    for seg in segment(messages, profile):
        key = seg.window_key()
        content = seg.content_hash()
        window = existing.get(key)

        if window is None:
            window = ExtractionWindow(
                tenant_id=tenant_id,
                thread_key=seg.thread_key,
                window_key=key,
                anchor_interaction_id=seg.anchor.id,
                started_at=seg.started_at,
                ended_at=seg.ended_at,
                message_count=len(seg.messages),
                content_hash=content,
                outcome="pending",
            )
            db.add(window)
            db.flush()
        else:
            window.thread_key = seg.thread_key
            window.anchor_interaction_id = seg.anchor.id
            window.started_at = seg.started_at
            window.ended_at = seg.ended_at
            window.message_count = len(seg.messages)
            if window.content_hash != content:
                window.content_hash = content
                # Leave `extracted_hash` alone — the difference between the two
                # is exactly what marks this window as needing another pass.
                if window.outcome != "curated":
                    window.outcome = "pending"

        for message in seg.messages:
            message.window_id = window.id
        windows.append(window)

    db.flush()
    return windows


def load_segment(db, window: ExtractionWindow) -> Segment:
    """Rebuild the Segment for a stored window, in message order."""
    messages = db.execute(
        select(Interaction)
        .where(Interaction.window_id == window.id)
        .order_by(Interaction.occurred_at.asc().nullslast(), Interaction.id.asc())
    ).scalars().all()
    return Segment(thread_key=window.thread_key or NO_THREAD, messages=messages)


def pending_windows(db, tenant_id: uuid.UUID) -> list[ExtractionWindow]:
    """Windows whose contents have changed since they were last extracted."""
    return db.execute(
        select(ExtractionWindow)
        .where(
            ExtractionWindow.tenant_id == tenant_id,
            ExtractionWindow.outcome != "curated",
            (ExtractionWindow.extracted_hash.is_(None))
            | (ExtractionWindow.extracted_hash != ExtractionWindow.content_hash),
        )
        .order_by(ExtractionWindow.started_at.asc().nullsfirst())
    ).scalars().all()
