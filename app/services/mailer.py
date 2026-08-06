"""Sending the digest by email.

stdlib smtplib rather than a provider SDK: one less dependency, one less
account to create before Thursday, and any transactional provider will accept
SMTP. If SMTP is not configured the digest is still composed and stored — it
just reports itself as unsent, because a missing mail server should not look
like a missing digest.

This is the *only* outbound channel in the system, and it goes to the owner.
Customers are never messaged — see BUILD_PROMPT constraint 1.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import settings


def configured() -> bool:
    return bool(settings().smtp_host and settings().digest_from)


def send_email(to: str, subject: str, text: str, html: str | None = None) -> tuple[bool, str]:
    """Returns (sent, detail). Never raises — a failed send is reported, not
    thrown, so one bad mailbox cannot abort a multi-tenant scheduled run."""
    if not configured():
        return False, "SMTP is not configured; digest stored but not emailed."
    if not to:
        return False, "Tenant has no email address on file."

    config = settings()
    message = EmailMessage()
    message["From"] = config.digest_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        if config.smtp_ssl:
            server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20)
        with server:
            if not config.smtp_ssl and config.smtp_starttls:
                server.starttls()
            if config.smtp_user:
                server.login(config.smtp_user, config.smtp_password)
            server.send_message(message)
        return True, f"Emailed to {to}."
    except Exception as exc:  # noqa: BLE001 - reported to the caller, never raised
        return False, f"{type(exc).__name__}: {exc}"
