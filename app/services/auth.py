"""Per-tenant bearer tokens.

The smallest thing that stops one tenant reading another's ledger. Not the
final story — owner sign-in (Firebase OTP) replaces this — but it moves the
tenant identity from something the caller asserts to something they have to
possess.

The token is stored only as a SHA-256 digest, so a database dump does not hand
over live credentials. Plain SHA-256 rather than bcrypt/argon2 is deliberate:
these are 256-bit random tokens, not passwords, so there is no dictionary to
slow down, and it keeps the dependency list where it is.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from sqlalchemy import select

from app.models.tenant import Tenant

TOKEN_BYTES = 32
PREFIX = "tex_"  # so a leaked token is greppable and obviously ours


def generate_token() -> str:
    return PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode()).hexdigest()


def issue_token(tenant: Tenant) -> str:
    """Mint a token for a tenant and store its digest.

    Returns the plaintext, which is the only time it exists — the caller must
    show it to the owner now or never.
    """
    token = generate_token()
    tenant.api_token_hash = hash_token(token)
    return token


def tenant_for_token(db, token: str | None) -> uuid.UUID | None:
    """Resolve a bearer token to a tenant id, or None."""
    if not token:
        return None
    return db.execute(
        select(Tenant.id).where(
            Tenant.api_token_hash == hash_token(token),
            Tenant.is_active.is_(True),
        )
    ).scalars().first()
