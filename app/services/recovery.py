"""Self-serve token recovery.

The obvious design is wrong. "Send me a new token" keyed on a phone number
means anyone who knows a business's number can rotate its token, and rotating
is destructive: the owner's phone is signed out immediately. A competitor with
a phone book could lock an owner out of their own books every morning.

So nothing rotates when recovery is *requested*. The request only sends a
short-lived signed link to the address already on file. The rotation happens
when that link is opened, which requires access to the inbox. Someone who
knows the number but not the mailbox can send the owner an email they did not
ask for, and nothing worse.

The link carries its own state — tenant id, an expiry, and an HMAC over both —
so there is no table to add and no row to clean up. It is signed with the
admin token, which means rotating that key also invalidates every outstanding
link, and that is the correct behaviour.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

from app.config import settings

# Long enough to find the email on a phone and tap it, short enough that a
# forwarded message stops working.
TTL_SECONDS = 30 * 60


class RecoveryError(Exception):
    """The link is expired, altered, or was never ours."""


def _key() -> bytes:
    secret = settings().admin_token
    if not secret:
        raise RecoveryError("Recovery is not configured on this deployment.")
    return hashlib.sha256(f"recovery:{secret}".encode()).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign(tenant_id: uuid.UUID, issued_at: int | None = None) -> str:
    """A single-use-shaped link payload: tenant, expiry, signature."""
    expires = (issued_at or int(time.time())) + TTL_SECONDS
    body = f"{tenant_id}.{expires}"
    digest = hmac.new(_key(), body.encode(), hashlib.sha256).digest()
    return f"{_b64(body.encode())}.{_b64(digest)}"


def verify(payload: str, now: int | None = None) -> uuid.UUID:
    """Return the tenant this link is for, or raise.

    Compared with compare_digest so a wrong signature cannot be found one byte
    at a time.
    """
    try:
        body_raw, sig_raw = payload.split(".", 1)
        body = _unb64(body_raw).decode()
        signature = _unb64(sig_raw)
        tenant_raw, expires_raw = body.rsplit(".", 1)
        expires = int(expires_raw)
    except Exception as exc:  # noqa: BLE001 - any malformed input is one error
        raise RecoveryError("This link is not valid.") from exc

    expected = hmac.new(_key(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise RecoveryError("This link is not valid.")

    if (now or int(time.time())) > expires:
        raise RecoveryError("This link has expired. Please ask for a new one.")

    try:
        return uuid.UUID(tenant_raw)
    except ValueError as exc:
        raise RecoveryError("This link is not valid.") from exc


def recovery_email(business_name: str, link: str) -> tuple[str, str]:
    text = f"""Getting back into Longbook

Someone asked for a new access token for {business_name}.

Open this link to get one:

{link}

The link works for 30 minutes and once only. Opening it issues a new token and
stops the old one working, so do not open it unless you actually need it.

If this was not you, you can ignore this email. Nothing has changed and your
current token still works.
"""
    html = f"""<html><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
color:#1a1917;line-height:1.55;max-width:560px">
<h2 style="margin:0 0 16px;font-weight:600">Getting back into Longbook</h2>
<p style="margin:0 0 16px">Someone asked for a new access token for
<strong>{business_name}</strong>.</p>
<p style="margin:0 0 20px">
  <a href="{link}" style="display:inline-block;background:#0d5c34;color:#fff;
     text-decoration:none;padding:12px 20px;border-radius:10px;font-weight:600">
     Get a new token</a>
</p>
<p style="margin:0 0 12px;color:#45433f">The link works for 30 minutes and once only.
Opening it issues a new token and <strong>stops the old one working</strong>, so do not
open it unless you actually need it.</p>
<p style="margin:0;color:#6f6c66;font-size:14px">If this was not you, ignore this email.
Nothing has changed and your current token still works.</p>
</body></html>"""
    return text, html
