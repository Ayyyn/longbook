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
from datetime import datetime

from fastapi import Response
from sqlalchemy import func, select
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.agents.analyst import Analyst
from app.models.conversation import ChatMessage, Conversation
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


# How much of the conversation the model is shown.
#
# This was 12, which was a guess dressed as a limit: it made the tenth question
# behave differently from the first for no reason the owner could see. Gemini's
# context is large and the turns are short — a hundred turns of this chat is a
# few thousand tokens, well under a rupee's worth across a whole conversation.
# The cap exists now only so an unbounded client cannot post a novel.
HISTORY_TURNS = 100


class Turn(BaseModel):
    role: str
    text: str


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    # When given, the conversation is loaded from the database and the client
    # need not carry history at all — which is what makes the same thread
    # readable from a different phone tomorrow.
    conversation_id: uuid.UUID | None = None
    # Truncated, never rejected. A hard cap here answered 422 to anyone who
    # asked ten questions in a row — the conversation simply stopped working,
    # with an error that says nothing about why. Too much history is our
    # problem to trim, not the owner's to avoid.
    history: list[Turn] = Field(default_factory=list, max_length=400)

    @field_validator("history")
    @classmethod
    def _recent_only(cls, turns: list[Turn]) -> list[Turn]:
        return turns[-HISTORY_TURNS:]


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
    # Returned so the next question in the thread can name it.
    conversation_id: uuid.UUID | None = None


class Suggestions(BaseModel):
    questions: list[str]


@router.get("/suggestions", response_model=Suggestions)
def suggestions(tid: TenantId) -> Suggestions:
    return Suggestions(questions=SUGGESTIONS)


@router.post("", response_model=Answer)
@router.post("/", response_model=Answer, include_in_schema=False)
def ask(payload: Ask, tid: TenantId, db: TenantDB, profile: Profile) -> Answer:
    started = time.perf_counter()

    conversation = _conversation(db, tid, payload.conversation_id, payload.question)

    # The stored thread is the source of truth. A client that sends history is
    # still honoured — the voice path has none to send — but it never overrides
    # what was actually said.
    history = _stored_history(db, tid, conversation.id) or [
        t.model_dump() for t in payload.history
    ]

    agent = Analyst(db, tid, profile)
    # execute(), not run() — this is logged to agent_run like every other
    # agent, so a question that goes wrong is as traceable as an extraction.
    decision = agent.execute({"question": payload.question, "history": history})

    output = decision.output or {}
    usage = (decision.meta or {}).get("usage") or {}
    latency = int((time.perf_counter() - started) * 1000)
    sources = output.get("sources") or []

    _remember(db, tid, conversation, payload.question, output, sources, latency,
              usage.get("cost_usd"))

    return Answer(
        answer=output.get("answer") or "",
        answered=bool(output.get("answered")),
        sources=[Source(**s) for s in sources],
        missing=output.get("missing"),
        latency_ms=latency,
        cost_usd=usage.get("cost_usd"),
        conversation_id=conversation.id,
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


# --- saved conversations -------------------------------------------------

def _title_from(question: str) -> str:
    """The first question, trimmed. No model call: a title nobody had to write
    is a title nobody has to read twice."""
    cleaned = " ".join((question or "").split())
    return (cleaned[:90] + "…") if len(cleaned) > 90 else (cleaned or "New conversation")


def _conversation(db, tenant_id, conversation_id, question):
    """The thread this question belongs to, creating one if it is the first."""
    if conversation_id:
        existing = db.get(Conversation, conversation_id)
        if existing is not None and existing.tenant_id == tenant_id:
            return existing
        # A stale id from an old tab starts a new thread rather than 404ing
        # mid-question. Losing the thread is bad; losing the answer is worse.

    conversation = Conversation(tenant_id=tenant_id, title=_title_from(question))
    db.add(conversation)
    db.flush()
    return conversation


def _stored_history(db, tenant_id, conversation_id) -> list[dict]:
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.tenant_id == tenant_id,
               ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    ).scalars().all()
    return [{"role": r.role, "text": r.text} for r in rows][-HISTORY_TURNS:]


def _remember(db, tenant_id, conversation, question, output, sources, latency, cost):
    """Both halves of the exchange, with the citations attached to the answer."""
    db.add(ChatMessage(tenant_id=tenant_id, conversation_id=conversation.id,
                       role="you", text=question))
    db.add(ChatMessage(
        tenant_id=tenant_id, conversation_id=conversation.id, role="answer",
        text=output.get("answer") or "", answered=bool(output.get("answered")),
        sources=sources, latency_ms=latency, cost_usd=cost,
    ))
    # Touched so the list orders by most recent activity, not creation.
    conversation.updated_at = datetime.utcnow()
    db.flush()


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    updated_at: datetime
    message_count: int


class StoredTurn(BaseModel):
    role: str
    text: str
    answered: bool | None = None
    sources: list[Source] = []
    latency_ms: int | None = None
    cost_usd: float | None = None


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(tid: TenantId, db: TenantDB, limit: int = 30) -> list[ConversationOut]:
    """Past threads, most recently used first."""
    counts = dict(db.execute(
        select(ChatMessage.conversation_id, func.count())
        .where(ChatMessage.tenant_id == tid)
        .group_by(ChatMessage.conversation_id)
    ).all())
    rows = db.execute(
        select(Conversation)
        .where(Conversation.tenant_id == tid)
        .order_by(Conversation.updated_at.desc())
        .limit(min(limit, 100))
    ).scalars().all()
    return [
        ConversationOut(id=c.id, title=c.title, updated_at=c.updated_at,
                        message_count=counts.get(c.id, 0))
        for c in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=list[StoredTurn])
def read_conversation(conversation_id: uuid.UUID, tid: TenantId,
                      db: TenantDB) -> list[StoredTurn]:
    """One thread, in order, with the citations each answer rested on."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tid:
        raise HTTPException(404, "No such conversation.")
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.tenant_id == tid,
               ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    ).scalars().all()
    return [
        StoredTurn(role=r.role, text=r.text, answered=r.answered,
                   sources=[Source(**s) for s in (r.sources or [])],
                   latency_ms=r.latency_ms, cost_usd=r.cost_usd)
        for r in rows
    ]


@router.delete("/conversations/{conversation_id}", status_code=204,
               response_class=Response)
def delete_conversation(conversation_id: uuid.UUID, tid: TenantId, db: TenantDB) -> Response:
    """Gone, with its messages, by the cascade on the row."""
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tid:
        raise HTTPException(404, "No such conversation.")
    db.delete(conversation)
    db.flush()
    return Response(status_code=204)
