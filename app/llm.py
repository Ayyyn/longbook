"""Gemini wrapper.

Single choke point for model calls so that token accounting, JSON repair, and
retry policy live in one place. Audio and images are passed to Gemini natively
rather than running a separate ASR/OCR step — context helps disambiguate trade
shorthand ("150 mtr @ 62 nett") far better than transcribe-then-parse.
"""

from __future__ import annotations

import io
import json
import logging
import os
import random
import re
import threading
import time
from typing import Any

from google import genai
from google.genai import types

from app.config import settings

log = logging.getLogger(__name__)

_client: genai.Client | None = None

# USD per 1M tokens. Update from the pricing page before relying on cost rollups.
# The `-latest` aliases move; they are priced as the tier they currently point
# at, so a cost rollup is an estimate whenever one is in use.
PRICING = {
    "gemini-2.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-2.5-pro": {"in": 1.25, "out": 10.00},
    "gemini-flash-latest": {"in": 0.30, "out": 2.50},
    "gemini-pro-latest": {"in": 1.25, "out": 10.00},
    "gemini-2.0-flash": {"in": 0.10, "out": 0.40},
    "gemini-2.5-flash-lite": {"in": 0.10, "out": 0.40},
    # ESTIMATE, carried over from the flash-lite tier — not confirmed against
    # the published price list. Cost rollups using it are indicative only.
    # Check before quoting a per-customer figure to anyone.
    "gemini-3.5-flash-lite": {"in": 0.10, "out": 0.40},
    "gemini-3.5-flash": {"in": 0.30, "out": 2.50},
    "gemini-3.6-flash": {"in": 0.30, "out": 2.50},
}

# Free-tier quota is per-minute and shared across every agent in the process,
# so pacing has to be global rather than per-caller.
_rate_lock = threading.Lock()
_last_call = 0.0


def _pace() -> None:
    """Space calls out to stay under the configured requests-per-minute."""
    global _last_call
    interval = 60.0 / max(settings().llm_rpm, 1)
    with _rate_lock:
        wait = _last_call + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _is_rate_limit(exc: Exception) -> bool:
    return "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)


def client() -> genai.Client:
    """The key comes from app.config, which reads .env — reading os.environ
    directly meant a key configured the documented way never arrived."""
    global _client
    if _client is None:
        key = settings().gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Put it in .env or the environment."
            )
        _client = genai.Client(api_key=key)
    return _client


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()


_unpriced: set[str] = set()


def _cost(model: str, usage: Any) -> float:
    p = PRICING.get(model)
    if not p and model and model not in _unpriced:
        # Silence here reads as "this run was free" on the Activity screen,
        # which is worse than a gap. Say so once per model per process.
        _unpriced.add(model)
        log.warning("No price for model %r — cost will be reported as 0.", model)
    if not p or not usage:
        return 0.0
    return round(
        (getattr(usage, "prompt_token_count", 0) / 1e6) * p["in"]
        + (getattr(usage, "candidates_token_count", 0) / 1e6) * p["out"],
        6,
    )


# Inline media is capped by the request size. Anything near it goes through
# the File API instead, which is a two-step upload and worth avoiding for the
# ordinary case — a photographed bill is well under a megabyte.
MAX_INLINE_MEDIA = 15 * 1024 * 1024


def _media_part(media_uri: str, media_kind: str, media_mime: str | None):
    """The attachment, as bytes.

    Not as a URI, which is what this used to do and which silently broke every
    photograph, PDF and voice note the product ever took in production. The
    Gemini Developer API — the one an API key authenticates — refuses a
    gs:// URI outright:

        Referencing Google Cloud Storage files directly is not supported.

    Only Vertex AI reads gs:// paths. That distinction cost us every media
    extraction: the window failed, the failure was recorded on the run and
    nowhere the owner could see, and the upload looked like it had been read.

    So the bytes are fetched through the service account and sent inline. It
    costs one GCS read per extraction, which is the correct price for the
    thing working.
    """
    from app.services.storage import read_media

    mime = media_mime or _mime(media_kind)
    if media_uri.startswith("http://") or media_uri.startswith("https://"):
        # A genuine public URL is the one case the API will fetch itself.
        return types.Part.from_uri(file_uri=media_uri, mime_type=mime)

    blob = read_media(media_uri)
    if len(blob) > MAX_INLINE_MEDIA:
        uploaded = client().files.upload(
            file=io.BytesIO(blob), config={"mime_type": mime}
        )
        return types.Part.from_uri(file_uri=uploaded.uri, mime_type=mime)
    return types.Part.from_bytes(data=blob, mime_type=mime)


def generate_json(
    *,
    model: str,
    system: str,
    user: str,
    media_uri: str | None = None,
    media_kind: str | None = None,
    examples: list[dict] | None = None,
    locale: str = "en",
    media_mime: str | None = None,
    max_retries: int = 2,
) -> tuple[dict, dict]:
    """Returns (parsed_json, usage_dict). Raises on unrecoverable parse failure."""

    parts: list[Any] = []
    if examples:
        parts.append(types.Part.from_text(
            text="Examples of correct output for this business:\n"
                 + "\n".join(json.dumps(e, ensure_ascii=False) for e in examples)
        ))
    parts.append(types.Part.from_text(text=user))

    if media_uri and media_kind in {"audio", "image", "document"}:
        parts.append(_media_part(media_uri, media_kind, media_mime))

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        _pace()
        try:
            resp = client().models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - rate limits are retried, rest re-raised
            if not _is_rate_limit(exc) or attempt == max_retries:
                raise
            # Exponential backoff with jitter: a synchronised retry storm across
            # a batch just burns the next minute's quota too.
            time.sleep(min(2**attempt * 8, 60) + random.uniform(0, 3))
            last_err = exc
            continue

        usage_raw = getattr(resp, "usage_metadata", None)
        usage = {
            "input_tokens": getattr(usage_raw, "prompt_token_count", 0),
            "output_tokens": getattr(usage_raw, "candidates_token_count", 0),
            "cost_usd": _cost(model, usage_raw),
        }
        try:
            return json.loads(_strip_fences(resp.text)), usage
        except json.JSONDecodeError as exc:
            last_err = exc

    raise ValueError(f"Model did not return valid JSON after retries: {last_err}")


def _mime(kind: str) -> str:
    return {"audio": "audio/ogg", "image": "image/jpeg", "document": "application/pdf"}[kind]


def _grounding(candidate) -> dict[str, Any] | None:
    """The pages a server-side search actually used, if it ran.

    Defensive throughout: grounding metadata is optional at every level, and a
    shape change here should cost us the citation, never the answer.
    """
    meta = getattr(candidate, "grounding_metadata", None)
    if meta is None:
        return None
    sources = []
    for chunk in getattr(meta, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        if web is None:
            continue
        uri = getattr(web, "uri", None)
        if not uri:
            continue
        sources.append({"title": getattr(web, "title", None) or uri, "url": uri})
    queries = list(getattr(meta, "web_search_queries", None) or [])
    if not sources and not queries:
        return None
    return {"queries": queries, "sources": sources}


def generate_with_tools(
    *,
    model: str,
    system: str,
    user: str,
    tools: dict[str, dict[str, Any]],
    history: list[dict[str, str]] | None = None,
    max_steps: int = 6,
    web_search: bool = False,
) -> tuple[str, list[dict[str, Any]], dict]:
    """Let the model decide what to look up, instead of guessing in advance.

    `tools` maps a name to {"declaration": FunctionDeclaration, "run": callable}.
    The callable receives only the arguments the model supplied; the database
    session and tenant id are closed over by the caller and are never
    reachable from a prompt. That boundary is the whole security story here:
    the model chooses *which question to ask*, never *whose data to ask it of*.

    Returns (answer_text, trace, usage) where trace is the ordered list of
    {tool, args, result_summary} — so an answer can be audited to the lookups
    behind it, the same way an extraction can be audited to its window.

    Bounded by max_steps because a loop that can call tools can also loop.
    """
    declarations = [spec["declaration"] for spec in tools.values()]
    tool_list = [types.Tool(function_declarations=declarations)]
    extra: dict[str, Any] = {}
    if web_search:
        # Google Search runs server-side: the model issues the query, Google
        # answers it, and the grounded text comes back within the same call —
        # there is no round trip for us to run. That is why it is not one of
        # `tools` and does not appear in the loop below.
        #
        # include_server_side_tool_invocations is load-bearing. Without it the
        # API rejects a built-in tool and function declarations in the same
        # request with a 400, which is a hard failure of the whole chat rather
        # than a missing search.
        tool_list.insert(0, types.Tool(google_search=types.GoogleSearch()))
        extra["tool_config"] = types.ToolConfig(include_server_side_tool_invocations=True)

    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.1,
        tools=tool_list,
        # Off: the loop is explicit so every call is logged and counted.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        **extra,
    )

    contents: list[Any] = []
    for turn in history or []:
        role = "model" if turn.get("role") == "assistant" else "user"
        contents.append(types.Content(
            role=role, parts=[types.Part.from_text(text=turn.get("content", ""))]
        ))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user)]))

    trace: list[dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "steps": 0}

    for _ in range(max_steps):
        _pace()
        resp = client().models.generate_content(
            model=model, contents=contents, config=config
        )
        usage = getattr(resp, "usage_metadata", None)
        totals["input_tokens"] += getattr(usage, "prompt_token_count", 0) or 0
        totals["output_tokens"] += getattr(usage, "candidates_token_count", 0) or 0
        totals["cost_usd"] = round(totals["cost_usd"] + _cost(model, usage), 6)
        totals["steps"] += 1

        candidate = (resp.candidates or [None])[0]
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        # A server-side search leaves its evidence in grounding metadata rather
        # than in a function response, so it is collected here instead of in
        # the loop below. Recorded as a trace entry like any other lookup: an
        # answer that leant on the web should be auditable to the pages it
        # leant on, exactly as one resting on records is auditable to the rows.
        found = _grounding(candidate)
        if found:
            trace.append({"tool": "web_search", "args": {"queries": found["queries"]},
                          "rows": len(found["sources"]), "sources": found["sources"]})

        if not calls:
            text = (getattr(resp, "text", None) or "").strip()
            return text, trace, totals

        contents.append(candidate.content)
        for call in calls:
            spec = tools.get(call.name)
            args = dict(call.args or {})
            if spec is None:
                payload = {"error": f"No such tool: {call.name}"}
            else:
                try:
                    payload = spec["run"](**args)
                except Exception as exc:  # noqa: BLE001 - a bad lookup is an answer
                    # Handed back rather than raised: the model can recover by
                    # asking differently, and a stack trace helps nobody here.
                    payload = {"error": f"{type(exc).__name__}: {exc}"}
            trace.append({"tool": call.name, "args": args,
                          "rows": len(payload.get("rows", [])) if isinstance(payload, dict) else 0})
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_function_response(
                    name=call.name, response=payload if isinstance(payload, dict) else {"result": payload}
                )],
            ))

    # Out of steps. Ask once for the best answer from what it already has,
    # rather than returning nothing after paying for six lookups.
    _pace()
    resp = client().models.generate_content(
        model=model,
        contents=[*contents, types.Content(role="user", parts=[types.Part.from_text(
            text="Answer now from what you have found. Do not call any more tools."
        )])],
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.1),
    )
    totals["steps"] += 1
    return (getattr(resp, "text", None) or "").strip(), trace, totals
