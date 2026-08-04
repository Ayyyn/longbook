"""WhatsApp chat export parser.

This is the onboarding magic trick: the owner exports a chat, and within a few
minutes they see their own last 90 days of orders and outstandings appear.
It is also the richest configuration signal the Configurator gets.

Export format varies by locale and platform. Handled here:
  [dd/mm/yy, hh:mm:ss AM] Sender: message
  dd/mm/yyyy, hh:mm - Sender: message
  dd/mm/yy, hh:mm am - Sender: message
Multi-line messages continue until the next timestamp line.
Attachments appear as "<attached: 00001-PHOTO-2026-08-04.jpg>" or
"IMG-20260804-WA0001.jpg (file attached)".
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

# Matches both bracketed (iOS) and dash (Android) export headers.
LINE_RE = re.compile(
    r"^\[?(?P<date>\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:[APap][Mm])?)\]?\s*[-–]?\s*"
    r"(?P<sender>[^:]{1,80}?):\s(?P<body>.*)$"
)

ATTACH_RE = re.compile(
    r"(?:<attached:\s*(?P<a>[^>]+)>)|(?P<b>[\w\-.]+\.(?:jpg|jpeg|png|opus|mp3|m4a|pdf))\s*\(file attached\)",
    re.IGNORECASE,
)

SYSTEM_NOISE = (
    "Messages and calls are end-to-end encrypted",
    "created group",
    "added you",
    "changed the subject",
    "joined using this group's invite link",
    "This message was deleted",
)

DATE_FORMATS = (
    "%d/%m/%Y %I:%M:%S %p", "%d/%m/%y %I:%M:%S %p",
    "%d/%m/%Y %I:%M %p",    "%d/%m/%y %I:%M %p",
    "%d/%m/%Y %H:%M:%S",    "%d/%m/%y %H:%M:%S",
    "%d/%m/%Y %H:%M",       "%d/%m/%y %H:%M",
)


@dataclass
class ParsedMessage:
    occurred_at: datetime | None
    sender: str
    body: str
    media_file: str | None
    media_kind: str  # image | audio | document | none


def _parse_ts(date_s: str, time_s: str) -> datetime | None:
    norm = f"{date_s.replace('.', '/').replace('-', '/')} {time_s.strip().upper()}"
    norm = re.sub(r"\s+", " ", norm)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(norm, fmt)
        except ValueError:
            continue
    return None


def _media_kind(filename: str | None) -> str:
    if not filename:
        return "none"
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext in {"jpg", "jpeg", "png", "webp"}:
        return "image"
    if ext in {"opus", "mp3", "m4a", "ogg", "aac"}:
        return "audio"
    return "document"


def parse_text(content: str) -> Iterator[ParsedMessage]:
    current: ParsedMessage | None = None

    for raw in content.splitlines():
        line = raw.replace("\u200e", "").replace("\u202f", " ").rstrip()
        if not line:
            continue

        m = LINE_RE.match(line)
        if m:
            if current:
                yield current
            body = m.group("body")
            if any(n in body for n in SYSTEM_NOISE):
                current = None
                continue

            am = ATTACH_RE.search(body)
            media = (am.group("a") or am.group("b")).strip() if am else None
            if am:
                body = ATTACH_RE.sub("", body).strip()

            current = ParsedMessage(
                occurred_at=_parse_ts(m.group("date"), m.group("time")),
                sender=m.group("sender").strip(),
                body=body,
                media_file=media,
                media_kind=_media_kind(media),
            )
        elif current:
            # continuation line of a multi-line message
            current.body = f"{current.body}\n{line}".strip()

    if current:
        yield current


def parse_export(path: str | Path) -> list[ParsedMessage]:
    """Accepts either the raw .txt or the .zip WhatsApp produces."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            content = z.read(name).decode("utf-8", errors="replace")
    else:
        content = path.read_text(encoding="utf-8", errors="replace")
    return list(parse_text(content))
