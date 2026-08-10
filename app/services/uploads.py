"""Taking several files at once, and saying what will happen before it does.

Two things an owner needs that a single-file endpoint cannot give them.

The first is honesty before they commit. Handing over six years of chats and
watching a spinner is a bad first minute; being told "4,812 messages, about
eight minutes" is a fine one. So parsing is separated from persisting, and the
estimate runs the real parser rather than guessing from file size.

The second is that records should start appearing early. Files are processed
largest first, because the big export is the one with the parties and the
history in it — sorting it last means ten minutes of an empty screen followed
by everything at once.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models.ingestion import Interaction
from app.services.intake import IntakeError, interactions_from_upload

# What the pacer actually achieves per window, measured against the real
# exports rather than assumed: ~10 model calls a minute, and a window is a
# handful of messages. Used only to set expectations, so erring slow is right.
MESSAGES_PER_MINUTE = 28


@dataclass
class FileEstimate:
    filename: str
    kind: str
    messages: int
    duplicates: int
    skipped: int
    media: int
    bytes: int
    error: str | None = None
    # Kept so a single-file caller can still answer 415 for a PDF rather
    # than flattening every unreadable file to one status.
    status_code: int = 400


@dataclass
class Estimate:
    files: list[FileEstimate] = field(default_factory=list)

    @property
    def new_messages(self) -> int:
        return sum(f.messages for f in self.files)

    @property
    def duplicates(self) -> int:
        return sum(f.duplicates for f in self.files)

    @property
    def media(self) -> int:
        return sum(f.media for f in self.files)

    @property
    def minutes(self) -> int:
        """Rounded up, never zero when there is anything to do."""
        if not self.new_messages:
            return 0
        return max(1, math.ceil(self.new_messages / MESSAGES_PER_MINUTE))


def _known_hashes(db, tenant_id: uuid.UUID, hashes: set[str]) -> set[str]:
    """Which of these messages the tenant already holds."""
    if not hashes:
        return set()
    found: set[str] = set()
    # Chunked: a six-year export is thousands of hashes and Postgres has a
    # limit on parameters in one statement.
    values = list(hashes)
    for start in range(0, len(values), 5000):
        chunk = values[start:start + 5000]
        rows = db.execute(
            select(Interaction.dedupe_hash).where(
                Interaction.tenant_id == tenant_id,
                Interaction.dedupe_hash.in_(chunk),
            )
        ).scalars().all()
        found.update(r for r in rows if r)
    return found


def parse_many(
    db,
    tenant_id: uuid.UUID,
    files: list[tuple[str, Path]],
    job_id: uuid.UUID,
) -> tuple[list[Interaction], Estimate]:
    """Parse every file, drop what is already held, and order the work.

    Returns unsaved rows plus a per-file account of what was found. A file
    that cannot be read does not sink the batch — the owner who picks four
    exports and one screenshot should get the four.
    """
    # Largest first, so the export with the history in it starts extracting
    # while the small ones are still being read.
    ordered = sorted(files, key=lambda f: f[1].stat().st_size, reverse=True)

    estimate = Estimate()
    # Each entry pairs the rows with *its own* estimate row. Indexing into
    # estimate.files instead would drift the moment a file fails to parse,
    # because failures land there and not in this list — and the counts would
    # then be written against the wrong filename.
    parsed: list[tuple[FileEstimate, list[Interaction]]] = []
    seen_in_batch: set[str] = set()

    for filename, path in ordered:
        size = path.stat().st_size
        try:
            intake = interactions_from_upload(tenant_id, filename, path, job_id)
        except IntakeError as exc:
            estimate.files.append(
                FileEstimate(filename, "unreadable", 0, 0, 0, 0, size,
                             exc.detail, exc.status_code)
            )
            continue

        # Duplicates within the batch too: people pick the same chat twice
        # when they are choosing files on a phone.
        rows: list[Interaction] = []
        batch_dupes = 0
        for row in intake.interactions:
            if row.dedupe_hash and row.dedupe_hash in seen_in_batch:
                batch_dupes += 1
                continue
            if row.dedupe_hash:
                seen_in_batch.add(row.dedupe_hash)
            rows.append(row)

        entry = FileEstimate(filename, intake.kind, len(rows), batch_dupes,
                             intake.skipped, intake.media, size)
        estimate.files.append(entry)
        parsed.append((entry, rows))

    already = _known_hashes(
        db, tenant_id,
        {r.dedupe_hash for _, rows in parsed for r in rows if r.dedupe_hash},
    )

    keep: list[Interaction] = []
    for entry, rows in parsed:
        fresh = [r for r in rows if not (r.dedupe_hash and r.dedupe_hash in already)]
        entry.duplicates += len(rows) - len(fresh)
        entry.messages = len(fresh)
        keep.extend(fresh)

    return keep, estimate


def estimate_only(db, tenant_id: uuid.UUID, files: list[tuple[str, Path]]) -> Estimate:
    """What would happen, without writing anything."""
    _, estimate = parse_many(db, tenant_id, files, uuid.uuid4())
    return estimate


def max_files() -> int:
    return settings().max_upload_files
