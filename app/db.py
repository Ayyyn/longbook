"""Engine, session factory, and the tenant isolation guard.

Isolation is enforced here rather than by convention. Inside `tenant_session()`
every ORM query gets a `tenant_id = :current` predicate injected, and every
flush is checked before it reaches Postgres. One forgotten `.where()` in a
handler is enough to show one trader their competitor's ledger, and that
mistake is invisible in review — so the session refuses to issue the query at
all rather than trusting each caller to remember.

The tenant is carried on `Session.info`, not in a ContextVar. FastAPI runs sync
dependencies and endpoints in a threadpool with copied contexts, so a
context-local would be reset in a different context than it was set in — and,
worse, could be invisible to the endpoint while looking perfectly correct here.
The session is the thing the event listeners are handed, so the session is
where the tenant lives.

Raw SQL bypasses this guard by definition (SQLAlchemy cannot see inside a
text() clause). Anything written as raw SQL — `app/services/matching.py`, for
one — must pass `tenant_id` itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria

from app.config import settings
from app.models.base import TenantScoped
from app.models.tenant import BusinessProfile, Tenant

engine = create_engine(
    settings().database_url,
    pool_pre_ping=True,  # Cloud Run idles connections out from under us
    future=True,
)

SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

_TENANT_KEY = "tenant_id"


class TenantIsolationError(RuntimeError):
    """A query or write would have crossed a tenant boundary."""


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def session_tenant(db: Session) -> uuid.UUID | None:
    """The tenant a session is scoped to, if any."""
    return db.info.get(_TENANT_KEY)


@contextmanager
def tenant_session(tenant_id: uuid.UUID | str) -> Iterator[Session]:
    """A session that can only see and write one tenant's rows.

    Commits on clean exit, rolls back on exception. This is the only session
    business code should use.
    """
    tid = _as_uuid(tenant_id)
    db = SessionFactory(info={_TENANT_KEY: tid})
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def admin_session() -> Iterator[Session]:
    """An unscoped session — no tenant filter is applied.

    Deliberately ugly to name and easy to grep for. Legitimate uses are tenant
    creation (there is no tenant yet) and cross-tenant scheduled jobs, which
    should loop over tenants and open a `tenant_session()` for each.
    """
    db = SessionFactory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state) -> None:
    """Inject `tenant_id = :current` into every ORM select/update/delete."""
    tid = state.session.info.get(_TENANT_KEY)
    if tid is None:
        return
    if state.is_column_load or state.is_relationship_load:
        # Deferred column and lazy relationship loads inherit the criteria of
        # the query that produced the parent object.
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return

    state.statement = state.statement.options(
        with_loader_criteria(TenantScoped, lambda cls: cls.tenant_id == tid, include_aliases=True),
        # Tenant and BusinessProfile predate the mixin (they *define* the
        # tenant rather than hanging off one), so they need naming explicitly.
        with_loader_criteria(
            BusinessProfile, lambda cls: cls.tenant_id == tid, include_aliases=True
        ),
        with_loader_criteria(Tenant, lambda cls: cls.id == tid, include_aliases=True),
    )


@event.listens_for(Session, "before_flush")
def _guard_flush(session: Session, flush_context, instances) -> None:
    """Stamp new rows with the current tenant; reject any row from another.

    The loader criteria above cannot catch writes, so pending objects are
    checked here — before the INSERT is built, so a mismatch fails loudly
    instead of landing in the wrong tenant's data.
    """
    tid = session.info.get(_TENANT_KEY)
    if tid is None:
        return

    for obj in session.new:
        _check_object(obj, tid, assign=True)
    for obj in session.dirty:
        if session.is_modified(obj, include_collections=False):
            _check_object(obj, tid, assign=False)
    for obj in session.deleted:
        _check_object(obj, tid, assign=False)


def _check_object(obj: object, tid: uuid.UUID, *, assign: bool) -> None:
    if isinstance(obj, Tenant):
        if obj.id is not None and _as_uuid(obj.id) != tid:
            raise TenantIsolationError(
                f"{type(obj).__name__} id={obj.id} written from a session scoped to {tid}"
            )
        return

    if not hasattr(obj, "tenant_id"):
        return

    owner = getattr(obj, "tenant_id", None)
    if owner is None:
        if assign:
            obj.tenant_id = tid  # type: ignore[attr-defined]
        return
    if _as_uuid(owner) != tid:
        raise TenantIsolationError(
            f"{type(obj).__name__} belongs to tenant {owner}, "
            f"but the session is scoped to {tid}"
        )
