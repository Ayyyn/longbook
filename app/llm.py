"""Gemini wrapper.

Single choke point for model calls so that token accounting, JSON repair, and
retry policy live in one place. Audio and images are passed to Gemini natively
rather than running a separate ASR/OCR step — context helps disambiguate trade
shorthand ("150 mtr @ 62 nett") far better than transcribe-then-parse.
"""

from __future__ import annotations

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
        parts.append(types.Part.from_uri(
            file_uri=media_uri, mime_type=media_mime or _mime(media_kind)
        ))

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
