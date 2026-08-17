"""Nylas: reading a connected mailbox.

Why Nylas and not Gmail directly. `gmail.readonly` is a restricted scope. Until
a CASA assessment is paid for and passed, the consent screen stays in Testing
mode, where refresh tokens expire after seven days — which means every business
reconnecting weekly and, worse, silently not syncing whenever they forget.
Nylas has already passed that assessment. The owner grants access to Nylas, we
hold a grant id, and the connection lasts until the owner revokes it.

What this module is and is not. It is a thin HTTP client plus one translation:
a Nylas message becomes an `InboundMail`, the same shape the IMAP forwarding
path produces. Everything after that — dedupe, attachment storage, windowing,
extraction — is the existing pipeline, unchanged. There is deliberately no
second ingest path for connected mail: a mailbox that syncs differently from a
forwarded mail is a mailbox whose bugs are its own.

No model calls here. This is transport.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.services.inbound import InboundMail

log = logging.getLogger(__name__)

# Nylas is a network call in the middle of a request the owner is waiting on.
# Long enough for a slow list, short enough that a hung provider does not hold
# a Cloud Run instance for the full request timeout.
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Matches the forwarding path's cap. Bigger attachments are almost always
# catalogues and video, and downloading them costs the sync more than the
# records they would produce are worth.
MAX_ATTACHMENT = 20 * 1024 * 1024

# One page of mail per sync per mailbox. A month of backfill on a busy inbox
# would otherwise arrive as one enormous extraction job; the watermark means
# the next run picks up where this one stopped, so nothing is lost by
# stopping early.
PAGE_SIZE = 50

# Attachments worth reading. A connected mailbox carries signatures, tracking
# pixels and logos on every single message — extracting those would fill the
# review queue with nothing and cost a model call each. Documents only.
DOCUMENT_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/csv",
)


def configured() -> bool:
    cfg = settings()
    return bool(cfg.nylas_client_id and cfg.nylas_api_key)


def _base() -> str:
    return settings().nylas_api_uri.rstrip("/")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings().nylas_api_key}",
        "Accept": "application/json",
    }


class NylasError(RuntimeError):
    """A call to Nylas failed. Carries the status so callers can tell a
    revoked grant (401/403) from a bad day (5xx)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _call(method: str, path: str, **kwargs) -> dict:
    url = f"{_base()}{path}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.request(method, url, headers=_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise NylasError(f"Could not reach Nylas: {exc}") from exc

    if resp.status_code >= 400:
        # Nylas puts the useful part in a JSON error body; fall back to text
        # for the proxy errors that never get that far.
        detail = resp.text[:300]
        try:
            body = resp.json()
            detail = str(body.get("error_description") or body.get("error") or detail)[:300]
        except Exception:  # noqa: BLE001 - a non-JSON error body is still an error
            pass
        raise NylasError(detail, resp.status_code)

    return resp.json() if resp.content else {}


# --------------------------------------------------------------------------
# Connecting
# --------------------------------------------------------------------------


def auth_url(redirect_uri: str, state: str) -> str:
    """Where to send the owner to grant access.

    `state` is ours and must come back unchanged. It is what binds the
    callback to the tenant that started it — without it, anyone who can reach
    the callback could attach their own mailbox to somebody else's books, or
    somebody else's mailbox to their own. See app/api/connect.py for the
    signing.
    """
    params = {
        "client_id": settings().nylas_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        # Offline, or there is no refresh and the grant dies with the session.
        "access_type": "offline",
        "state": state,
    }
    return f"{_base()}/v3/connect/auth?{urlencode(params)}"


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Turn the one-time code into a grant.

    Returns the raw Nylas payload; the caller takes `grant_id` and `email`
    from it. The access token in the response is deliberately ignored — the
    API key authenticates every later call, so there is no second credential
    to store or refresh.
    """
    payload = {
        "client_id": settings().nylas_client_id,
        "client_secret": settings().nylas_api_key,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    return _call("POST", "/v3/connect/token", json=payload)


def grant(grant_id: str) -> dict:
    """Details of one grant — used to confirm it is still alive."""
    return _call("GET", f"/v3/grants/{grant_id}").get("data", {})


def revoke(grant_id: str) -> None:
    """Disconnect. Best-effort: a grant Nylas has already dropped 404s, and
    that is the state we wanted anyway."""
    try:
        _call("DELETE", f"/v3/grants/{grant_id}")
    except NylasError as exc:
        if exc.status not in (401, 403, 404):
            raise


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def list_messages(grant_id: str, since: datetime | None, limit: int = PAGE_SIZE) -> list[dict]:
    """Messages received at or after `since`, oldest first.

    Oldest first matters: the sync stops after one page, and the watermark
    advances to the newest message it actually took. Newest-first paging would
    move the watermark past mail that was never read.
    """
    params: dict = {"limit": limit}
    if since is not None:
        # Nylas takes whole seconds since the epoch. `since` is naive UTC,
        # like every other datetime in this system.
        params["received_after"] = int(since.replace(tzinfo=timezone.utc).timestamp())
    data = _call("GET", f"/v3/grants/{grant_id}/messages", params=params).get("data", [])
    return sorted(data, key=lambda m: m.get("date") or 0)


def download_attachment(grant_id: str, attachment_id: str, message_id: str) -> bytes:
    url = f"{_base()}/v3/grants/{grant_id}/attachments/{attachment_id}/download"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, headers=_headers(), params={"message_id": message_id})
    except httpx.HTTPError as exc:
        raise NylasError(f"Could not reach Nylas: {exc}") from exc
    if resp.status_code >= 400:
        raise NylasError(resp.text[:200], resp.status_code)
    return resp.content


# --------------------------------------------------------------------------
# Translation
# --------------------------------------------------------------------------


def _address(entries) -> str:
    """First "Name <addr>" out of a Nylas participant list."""
    if not entries:
        return ""
    first = entries[0] if isinstance(entries, list) else entries
    if not isinstance(first, dict):
        return str(first)
    email = first.get("email") or ""
    name = first.get("name") or ""
    return f"{name} <{email}>".strip() if name else email


def _body_text(message: dict) -> str:
    """Readable text out of whatever the provider sent.

    Nylas returns `body` as HTML for most providers. Extraction reads this as
    prose, and raw markup is both noise and tokens — so tags come out. The
    snippet is the fallback for the messages that have no body at all.
    """
    body = message.get("body") or ""
    if "<" in body and ">" in body:
        import re

        # Drop the parts that are never content before touching the rest,
        # or a stylesheet ends up in the extraction window as a wall of text.
        body = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", body)
        body = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        import html as html_mod

        body = html_mod.unescape(body)
        body = re.sub(r"[ \t\xa0]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body or (message.get("snippet") or "")


def _decoded_date(message: dict) -> str | None:
    """RFC 2822, because that is what `store_mail` parses."""
    stamp = message.get("date")
    if not stamp:
        return None
    try:
        from email.utils import format_datetime

        return format_datetime(datetime.fromtimestamp(int(stamp), tz=timezone.utc))
    except Exception:  # noqa: BLE001 - a nonsense date is not worth failing on
        return None


def to_inbound(grant_id: str, message: dict, *, with_attachments: bool = True) -> InboundMail:
    """One Nylas message as the shape the forwarding path already produces.

    The slug is empty: `store_mail` is called with an explicit tenant id for
    connected mail, because we know whose mailbox it is. Only the shared
    forwarding address has to work out the tenant from a +tag.
    """
    attachments: list[tuple[str, str, bytes]] = []
    if with_attachments:
        for item in message.get("attachments") or []:
            mime = (item.get("content_type") or "").split(";")[0].strip().lower()
            name = item.get("filename") or ""
            size = int(item.get("size") or 0)
            if item.get("is_inline"):
                continue  # signature logos and tracking pixels
            if not (mime.startswith("image/") or mime in DOCUMENT_TYPES):
                continue
            if size > MAX_ATTACHMENT:
                log.info("nylas: skipping %s (%d bytes)", name, size)
                continue
            try:
                blob = download_attachment(grant_id, item["id"], message["id"])
            except (NylasError, KeyError) as exc:
                # One unreadable attachment must not cost us the mail body,
                # which is usually where the order is anyway.
                log.warning("nylas: attachment %s failed: %s", name, exc)
                continue
            attachments.append((name, mime, blob))

    return InboundMail(
        slug="",
        subject=message.get("subject") or "",
        sender=_address(message.get("from")),
        body=_body_text(message),
        occurred_at=_decoded_date(message),
        attachments=attachments,
    )


def received_at(message: dict) -> datetime | None:
    """The message's date as naive UTC, for the watermark."""
    stamp = message.get("date")
    if not stamp:
        return None
    try:
        return datetime.fromtimestamp(int(stamp), tz=timezone.utc).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return None


def default_since() -> datetime:
    return datetime.utcnow() - timedelta(days=settings().nylas_initial_days)


# Kept next to the client because it is the same concern: `state` has to
# survive a round trip through the provider's redirect and come back provably
# ours. Signed rather than stored — a row per in-flight connection would need
# expiring, and this needs no cleanup.
def sign_state(tenant_id: str, secret: str, issued: int) -> str:
    import hashlib
    import hmac

    raw = f"{tenant_id}:{issued}"
    mac = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(f"{raw}:{mac}".encode()).decode().rstrip("=")


def read_state(state: str, secret: str, max_age: int = 900) -> str | None:
    """The tenant id inside a state we signed, or None. Never raises —
    every failure is the same answer, so a forged state and a mangled one
    are indistinguishable from the outside."""
    import hashlib
    import hmac
    import time

    try:
        padded = state + "=" * (-len(state) % 4)
        tenant_id, issued, mac = base64.urlsafe_b64decode(padded).decode().rsplit(":", 2)
        expected = hmac.new(
            secret.encode(), f"{tenant_id}:{issued}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(mac, expected):
            return None
        if time.time() - int(issued) > max_age:
            return None
        return tenant_id
    except Exception:  # noqa: BLE001 - any malformed state is simply invalid
        return None
