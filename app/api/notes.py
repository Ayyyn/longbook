"""The notes screen.

Nothing here extracts, resolves or commits. A note is the owner's own words,
kept as written — the one place in this product where the machine does not
have an opinion about what was said.

The exception is dictation, and even that is deliberately one-way: audio is
transcribed and handed *back to the typing box* rather than saved directly, so
what gets stored is what the owner approved. Speech recognition on three
languages in one sentence is wrong often enough that saving its first attempt
would be putting words in someone's mouth.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import TenantDB, TenantId
from app.models.note import Note

# Prefix and access gating are applied in main.py, like every other router.
router = APIRouter()

# Same instruction the spoken-question path uses. A trader saying "Ashok ko
# SR-1042 ka kya rate diya tha" is three languages in one sentence, and an ASR
# tuned for one of them flattens exactly the words that matter.
TRANSCRIBE = """Write out exactly what is said in this recording.

The speaker is an Indian business owner. They will mix Hindi, Gujarati,
Marathi and English in the same sentence, and that is normal — keep the words
they used rather than translating. Names, item codes and numbers matter most;
get those exactly right.

Return JSON: {"text": "<what was said>"}"""


class NoteOut(BaseModel):
    id: uuid.UUID
    body: str | None
    caption: str | None
    media_kind: str | None
    media_url: str | None
    source: str
    created_at: datetime


class Transcript(BaseModel):
    text: str


def _to_out(note: Note) -> NoteOut:
    return NoteOut(
        id=note.id, body=note.body, caption=note.caption,
        media_kind=note.media_kind,
        # Served through the API rather than as a gs:// path the browser
        # cannot fetch, and never as a public URL.
        media_url=f"/api/notes/{note.id}/media" if note.media_uri else None,
        source=note.source or "typed", created_at=note.created_at,
    )


@router.get("", response_model=list[NoteOut])
@router.get("/", response_model=list[NoteOut], include_in_schema=False)
def list_notes(tid: TenantId, db: TenantDB, limit: int = 200) -> list[NoteOut]:
    rows = db.execute(
        select(Note).where(Note.tenant_id == tid)
        .order_by(Note.created_at.desc()).limit(min(limit, 500))
    ).scalars().all()
    return [_to_out(n) for n in rows]


@router.post("", response_model=NoteOut, status_code=201)
@router.post("/", response_model=NoteOut, status_code=201, include_in_schema=False)
def create_note(
    tid: TenantId,
    db: TenantDB,
    body: str = Form(""),
    caption: str = Form(""),
    source: str = Form("typed"),
    file: UploadFile | None = File(None),
) -> NoteOut:
    """A note is text, a photo, or both. Empty is not a note."""
    from app.services.intake import IMAGE_MIMES, _audio_mime
    from app.services.storage import store_media

    text = (body or "").strip()
    media_uri = media_kind = media_mime = None

    if file is not None and file.filename:
        raw = file.file.read()
        if raw:
            suffix = "." + file.filename.rsplit(".", 1)[-1].lower()
            media_uri = store_media(tid, file.filename, raw)
            if suffix in IMAGE_MIMES:
                media_kind, media_mime = "image", IMAGE_MIMES[suffix]
            else:
                media_kind, media_mime = "audio", _audio_mime(suffix)

    if not text and not media_uri:
        raise HTTPException(400, "A note needs some words or a picture.")

    note = Note(
        tenant_id=tid, body=text or None, caption=(caption or "").strip() or None,
        media_uri=media_uri, media_kind=media_kind, media_mime=media_mime,
        source=source if source in {"typed", "voice", "photo"} else "typed",
    )
    db.add(note)
    db.flush()
    return _to_out(note)


@router.get("/{note_id}/media")
def note_media(note_id: uuid.UUID, tid: TenantId, db: TenantDB) -> Response:
    """The attached file, read through the tenant's own session.

    Storage is private and stays private: nothing here mints a public link, so
    a photo of somebody's ledger cannot leak by URL.
    """
    from app.services.storage import read_media

    note = db.get(Note, note_id)
    if note is None or note.tenant_id != tid or not note.media_uri:
        raise HTTPException(404, "No such note.")
    try:
        data = read_media(note.media_uri)
    except Exception as exc:  # noqa: BLE001 - a missing object is a 404, not a 500
        raise HTTPException(404, "That file is no longer stored.") from exc
    return Response(content=data, media_type=note.media_mime or "application/octet-stream")


@router.delete("/{note_id}", status_code=204, response_class=Response)
def delete_note(note_id: uuid.UUID, tid: TenantId, db: TenantDB) -> Response:
    note = db.get(Note, note_id)
    if note is None or note.tenant_id != tid:
        raise HTTPException(404, "No such note.")
    db.delete(note)
    db.flush()
    return Response(status_code=204)


@router.post("/transcribe", response_model=Transcript)
def transcribe(tid: TenantId, db: TenantDB, file: UploadFile = File(...)) -> Transcript:
    """Speech to text, handed back for the owner to correct before it is saved.

    Deliberately not "record a voice note and store it": what gets kept should
    be what the owner meant, and dictation across three languages is wrong
    often enough that saving the first attempt puts words in their mouth.
    """
    from app.config import settings
    from app.llm import generate_json
    from app.services.intake import _audio_mime
    from app.services.storage import store_media

    raw = file.file.read()
    if not raw:
        raise HTTPException(400, "The recording was empty.")

    suffix = "." + (file.filename or "note.ogg").rsplit(".", 1)[-1].lower()
    uri = store_media(tid, file.filename or f"note-{uuid.uuid4().hex}.ogg", raw)
    try:
        heard, _usage = generate_json(
            model=settings().model_fast,
            system=TRANSCRIBE,
            user="Write out what is said.",
            media_uri=uri,
            media_kind="audio",
            media_mime=_audio_mime(suffix),
        )
    except Exception as exc:  # noqa: BLE001 - reported, not raised at the owner
        raise HTTPException(
            502, "Could not make out the recording. Try again, or type it."
        ) from exc

    text = (heard.get("text") or "").strip()
    if not text:
        raise HTTPException(422, "Nothing was audible. Try again a bit closer.")
    return Transcript(text=text)
