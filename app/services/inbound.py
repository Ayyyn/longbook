"""Mail forwarded in by the owner, read from one mailbox we control.

Why this exists rather than only OAuth: `gmail.readonly` is a restricted
scope, so until a CASA assessment is paid for, the consent screen stays in
Testing mode — and in Testing mode **refresh tokens expire after seven days**.
Every customer would have to reconnect their mailbox weekly, and the ones who
did not would silently stop syncing. That is not a primary path.

Forwarding has none of that. Each tenant gets a plus-addressed alias on our
own mailbox — `ops+<slug>@…` — and the owner either forwards the invoice by
hand or sets one Gmail filter to auto-forward. There is no token, nothing to
expire, no consent screen, and no cap on how many businesses can use it.

It also avoids needing a domain of our own. Plus-addressing gives a unique,
routable address per tenant on an account that already exists, which means
this works today rather than after a DNS purchase. Owning a domain and
routing `*@inbound.textileops.in` is the upgrade, and it changes only
`address_for()` and the header parsing below.
"""

from __future__ import annotations

import email
import hashlib
import imaplib
import logging
import uuid
from dataclasses import dataclass, field
from email.header import decode_header, make_header
from email.message import Message

from app.config import settings

log = logging.getLogger(__name__)

# Attachments worth reading. Anything else is decoration — signatures, logos,
# tracking pixels — and putting it through the document pipeline wastes a
# model call on a company letterhead.
DOCUMENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "image/jpeg",
    "image/png",
    "image/webp",
}

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def slug_for(tenant_id: uuid.UUID) -> str:
    """A short, stable, non-sequential tag for a tenant's alias.

    Derived rather than random so it can be recomputed if the column is ever
    lost, and hashed so it does not expose a tenant id to anyone who reads an
    email header.
    """
    digest = hashlib.sha256(f"inbound:{tenant_id}".encode()).hexdigest()
    return digest[:10]


def address_for(slug: str) -> str | None:
    """The address an owner forwards to, or None if inbound is not configured."""
    box = settings().inbound_address
    if not box or "@" not in box:
        return None
    local, domain = box.rsplit("@", 1)
    return f"{local}+{slug}@{domain}"


def configured() -> bool:
    return bool(settings().inbound_address and settings().inbound_password)


@dataclass
class InboundMail:
    slug: str
    subject: str
    sender: str
    body: str
    occurred_at: str | None
    attachments: list[tuple[str, str, bytes]] = field(default_factory=list)


def _text(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 - a malformed header is not worth failing on
        return str(value)


def _slug_from(message: Message) -> str | None:
    """Find the +tag the mail was delivered to.

    Checked across several headers because the one that carries the alias
    depends on how it arrived: a hand-forward puts it in To, a Gmail
    auto-forward filter puts it in Delivered-To, and some relays only set
    X-Original-To.
    """
    for header in ("Delivered-To", "X-Original-To", "To", "Cc", "X-Forwarded-To"):
        for raw in message.get_all(header) or []:
            for _, addr in email.utils.getaddresses([str(raw)]):
                if "+" in addr and "@" in addr:
                    local = addr.rsplit("@", 1)[0]
                    tag = local.split("+", 1)[1].strip().lower()
                    if tag:
                        return tag
    return None


def _body_of(message: Message) -> str:
    """Prefer the plain-text part; fall back to stripping the HTML crudely."""
    if not message.is_multipart():
        payload = message.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")

    html = ""
    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if kind == "text/plain":
            return text
        if kind == "text/html" and not html:
            html = text

    if html:
        import re

        stripped = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        return re.sub(r"\s+", " ", stripped).strip()
    return ""


def parse_message(raw: bytes) -> InboundMail | None:
    """Turn a raw mail into the parts we care about, or None if unaddressed."""
    message = email.message_from_bytes(raw)
    slug = _slug_from(message)
    if not slug:
        return None

    attachments: list[tuple[str, str, bytes]] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() != "attachment":
                continue
            kind = (part.get_content_type() or "").lower()
            if kind not in DOCUMENT_TYPES:
                continue
            payload = part.get_payload(decode=True) or b""
            if not payload or len(payload) > MAX_ATTACHMENT_BYTES:
                continue
            attachments.append((_text(part.get_filename()) or "attachment", kind, payload))

    return InboundMail(
        slug=slug,
        subject=_text(message.get("Subject")),
        sender=_text(message.get("From")),
        body=_body_of(message).strip(),
        occurred_at=message.get("Date"),
        attachments=attachments,
    )


def fetch_unseen(limit: int = 100) -> list[InboundMail]:
    """Read unseen mail and mark it seen. Never raises.

    Marking seen is the only thing standing between a transient failure and
    the same invoice being read every five minutes for ever, so it happens
    per message, immediately after that message has been parsed.
    """
    if not configured():
        return []

    cfg = settings()
    out: list[InboundMail] = []
    try:
        client = imaplib.IMAP4_SSL(cfg.inbound_host, cfg.inbound_port, timeout=30)
        client.login(cfg.inbound_address, cfg.inbound_password)
        client.select("INBOX")
        status, data = client.search(None, "UNSEEN")
        if status != "OK":
            client.logout()
            return []

        ids = (data[0] or b"").split()[:limit]
        for message_id in ids:
            status, payload = client.fetch(message_id, "(RFC822)")
            if status != "OK" or not payload or not payload[0]:
                continue
            parsed = parse_message(payload[0][1])
            # Marked seen either way: mail addressed to no tenant is not going
            # to become addressed later, and leaving it unseen means reading
            # it again on every run.
            client.store(message_id, "+FLAGS", "\\Seen")
            if parsed:
                out.append(parsed)
        client.logout()
    except Exception:  # noqa: BLE001 - a mailbox problem must not break the run
        log.exception("Could not read the inbound mailbox.")
    return out
