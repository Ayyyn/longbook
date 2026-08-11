"""Ask a question about this business's own records.

Conversation memory is carried by the client rather than stored: the session
is a handful of turns, it belongs to one device, and a table of chat history
would be another store of customer text to secure, retain and delete for no
benefit the owner can see. The server trusts the history for phrasing only —
every fact still has to come from a fresh, tenant-filtered query.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.agents.analyst import Analyst
from app.api.deps import Profile, TenantDB, TenantId

router = APIRouter()

# What an owner is likely to want on day one, in their words rather than ours.
# Trade-neutral by construction. "What did we last quote for cotton?" is a
# fine question for a fabric trader and a baffling one for a bearing dealer,
# and the suggestions are the first thing a new owner reads.
SUGGESTIONS = [
    "Who owes me the most?",
    "Which orders haven't been dispatched?",
    "Who has crossed their credit days?",
    "What did we last quote this party?",
    "What came in this week?",
]


class Turn(BaseModel):
    role: str
    text: str


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=12)


class Source(BaseModel):
    ref: str
    kind: str
    label: str
    detail: str
    party_id: str | None = None
    order_id: str | None = None
    interaction_id: str | None = None
    occurred_at: str | None = None


class Answer(BaseModel):
    # Echoed back for a spoken question so the owner can see what was heard.
    question: str | None = None
    answer: str
    answered: bool
    sources: list[Source]
    missing: str | None = None
    # Surfaced because this runs on demand and has to feel fast; a question
    # that costs more than it is worth should be visible, not buried in logs.
    latency_ms: int
    cost_usd: float | None = None


class Suggestions(BaseModel):
    questions: list[str]


@router.get("/suggestions", response_model=Suggestions)
def suggestions(tid: TenantId) -> Suggestions:
    return Suggestions(questions=SUGGESTIONS)


@router.post("", response_model=Answer)
@router.post("/", response_model=Answer, include_in_schema=False)
def ask(payload: Ask, tid: TenantId, db: TenantDB, profile: Profile) -> Answer:
    started = time.perf_counter()

    agent = Analyst(db, tid, profile)
    # execute(), not run() — this is logged to agent_run like every other
    # agent, so a question that goes wrong is as traceable as an extraction.
    decision = agent.execute(
        {
            "question": payload.question,
            "history": [t.model_dump() for t in payload.history],
        }
    )

    output = decision.output or {}
    usage = (decision.meta or {}).get("usage") or {}
    return Answer(
        answer=output.get("answer") or "",
        answered=bool(output.get("answered")),
        sources=[Source(**s) for s in output.get("sources") or []],
        missing=output.get("missing"),
        latency_ms=int((time.perf_counter() - started) * 1000),
        cost_usd=usage.get("cost_usd"),
    )


TRANSCRIBE = """Write out exactly what is said in this recording, as one line.

The speaker is an Indian business owner. They will mix Hindi, Gujarati,
Marathi and English in the same sentence, and that is normal — keep the words
they used rather than translating. Item codes and numbers matter most; get
those exactly right.

Return JSON: {"question": "..."}"""


@router.post("/voice", response_model=Answer)
def ask_by_voice(
    tid: TenantId,
    db: TenantDB,
    profile: Profile,
    file: UploadFile = File(...),
) -> Answer:
    """Ask out loud.

    The recording goes to Gemini as audio rather than through a separate
    speech-to-text step. A trader saying "Ashok ko SR-1042 ka kya rate diya
    tha" is three languages in one sentence, and an ASR tuned for one of them
    flattens exactly the words the question turns on.
    """
    from app.config import settings
    from app.llm import generate_json
    from app.services.intake import _audio_mime
    from app.services.storage import store_media

    started = time.perf_counter()
    raw = file.file.read()
    if not raw:
        raise HTTPException(400, "The recording was empty.")

    suffix = "." + (file.filename or "note.ogg").rsplit(".", 1)[-1].lower()
    uri = store_media(tid, file.filename or f"question-{uuid.uuid4().hex}.ogg", raw)

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
            502, "Could not make out the recording. Try again, or type the question."
        ) from exc

    question = (heard.get("question") or "").strip()
    if not question:
        raise HTTPException(
            422, "Nothing was audible in that recording. Try again a bit closer."
        )

    agent = Analyst(db, tid, profile)
    decision = agent.execute({"question": question, "history": []})
    output = decision.output or {}
    usage = (decision.meta or {}).get("usage") or {}

    return Answer(
        question=question,
        answer=output.get("answer") or "",
        answered=bool(output.get("answered")),
        sources=[Source(**s) for s in output.get("sources") or []],
        missing=output.get("missing"),
        latency_ms=int((time.perf_counter() - started) * 1000),
        cost_usd=usage.get("cost_usd"),
    )
