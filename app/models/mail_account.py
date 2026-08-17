"""A mailbox this business has connected, read through Nylas.

Forwarding (see app/services/inbound.py) asks the owner to remember to forward.
A connected mailbox does not: once granted, the invoices and purchase orders
that arrive by mail become records without anybody doing anything. That is the
difference between a system that reflects the business and one that reflects
how diligent somebody was about forwarding.

What is stored here is a *grant id*, not a password and not a Google refresh
token. Nylas holds the provider credential; the grant id is the handle we use
to ask for this mailbox's messages. It is still credential-equivalent — anyone
holding it can read the mail — so it never leaves the server: no endpoint
returns it, and it is not in any response model.

One row per connected mailbox. A tenant may have more than one (the owner's
and the accounts desk's), which is why this is a table and not two columns on
Tenant.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, String

from app.models.base import Base, TenantScoped


class MailAccount(Base, TenantScoped):
    __tablename__ = "mail_account"

    # "google" | "microsoft" | "imap" — what Nylas reports the grant is for.
    # Display only; the sync path is identical for all of them.
    provider = Column(String(32))

    # The address the owner connected, shown back to them so they can tell
    # which mailbox this is. The only part of the grant that is safe to show.
    email = Column(String(200))

    # The Nylas handle for this mailbox. Never returned by any endpoint.
    grant_id = Column(String(80), index=True)

    # "active" once the grant works, "revoked" once Nylas says it does not.
    # A revoked row is kept rather than deleted so the owner is told their
    # mail stopped syncing instead of quietly seeing nothing new.
    status = Column(String(16), default="active")

    # The watermark. Nylas filters by received_after in whole seconds, so this
    # is the received-at of the newest message we have taken, and the next
    # sync asks for everything at or after it. Overlap of a second is fine —
    # store_mail dedupes on content — whereas a gap loses mail silently.
    synced_through = Column(DateTime, nullable=True)

    # When we last successfully talked to Nylas at all, which is a different
    # question from whether there was new mail.
    last_checked_at = Column(DateTime, nullable=True)

    # Last error text, so a mailbox that stopped working can say why.
    last_error = Column(String(300))
