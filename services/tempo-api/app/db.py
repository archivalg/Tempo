"""Database engine, session and tenant context (ADR-0011: PostgreSQL + RLS).

Tenant containment is two layers. Application predicates stay mandatory for
behaviour and performance; PostgreSQL row-level security is the independent
layer. RLS policies (alembic 0002) read transaction-local settings that this
module sets *after* the caller is authenticated:

    app.tenant_id    the authorised tenant (absent => policies match nothing)
    app.auth_lookup  'on' only inside app.core.auth's principal-resolution phase

The settings are `set_config(..., is_local=true)`, so they vanish at commit/
rollback and can never leak to the next user of a pooled connection.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings, settings


def build_engine_kwargs(database_url: str, config: Settings) -> dict:
    """Pooling/timeout config. Pure function so tests exercise every branch."""
    if not database_url.startswith("postgresql"):
        raise ValueError("Tempo supports PostgreSQL only (ADR-0011)")
    return {
        "pool_pre_ping": config.db_pool_pre_ping,
        "pool_size": config.db_pool_size,
        "max_overflow": config.db_max_overflow,
        "pool_timeout": config.db_pool_timeout_seconds,
        "pool_recycle": config.db_pool_recycle_seconds,
        "connect_args": {"options": f"-c statement_timeout={config.db_statement_timeout_ms}"},
    }


engine = create_engine(settings.database_url, **build_engine_kwargs(settings.database_url, settings))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


_TENANT_KEY = "tempo.tenant_id"
_AUTH_KEY = "tempo.auth_lookup"
_SITES_KEY = "tempo.site_scope"
NO_SITES = "!none"  # a caller with no site grants matches no site-keyed row (never "everything")


def _apply_context(session: Session, connection) -> None:
    tenant_id = session.info.get(_TENANT_KEY)
    if tenant_id:
        connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
    if session.info.get(_AUTH_KEY):
        connection.execute(text("SELECT set_config('app.auth_lookup', 'on', true)"))
    sites = session.info.get(_SITES_KEY)
    if sites:
        connection.execute(text("SELECT set_config('app.site_scope', :s, true)"), {"s": sites})


@event.listens_for(Session, "after_begin")
def _on_begin(session: Session, transaction, connection) -> None:
    _apply_context(session, connection)


def bind_tenant(session: Session, tenant_id: str) -> None:
    """Scope this session (this and every later transaction) to one tenant.

    Call only after trusted authorisation. Ends the auth-lookup phase.
    """
    if not tenant_id:
        raise ValueError("tenant_id required")
    session.info[_TENANT_KEY] = tenant_id
    session.info.pop(_AUTH_KEY, None)
    conn = session.connection()
    conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})
    conn.execute(text("SELECT set_config('app.auth_lookup', 'off', true)"))


def bind_sites(session: Session, site_ids: list[str] | tuple[str, ...] | None) -> None:
    """Narrow this session to the caller's granted sites for every site-keyed table (defence in depth under the handlers' own checks).

    `None` leaves the session tenant-wide, which only trusted internal paths (workers, CLI, seeding) may use.
    An empty list means *no* sites, not all of them."""
    if site_ids is None:
        session.info.pop(_SITES_KEY, None)
        return
    if any("," in x for x in site_ids):
        raise ValueError("site ids must not contain commas")
    value = ",".join(sorted(set(site_ids))) or NO_SITES
    session.info[_SITES_KEY] = value
    session.connection().execute(text("SELECT set_config('app.site_scope', :s, true)"), {"s": value})


def begin_auth_lookup(session: Session) -> None:
    """Principal-resolution phase: may read identity tables across tenants, nothing else."""
    session.info[_AUTH_KEY] = True
    session.connection().execute(text("SELECT set_config('app.auth_lookup', 'on', true)"))


@contextmanager
def tenant_session(tenant_id: str) -> Iterator[Session]:
    """For workers/background jobs: a session scoped to one tenant via RLS."""
    db = SessionLocal()
    try:
        bind_tenant(db, tenant_id)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Import models so metadata is complete. Schema is created only by Alembic."""
    import app.models.attendance  # noqa: F401
    import app.models.canonical  # noqa: F401
    import app.models.connectors  # noqa: F401
    import app.models.directory  # noqa: F401
    import app.models.rosters  # noqa: F401
    import app.models.identity  # noqa: F401
    import app.models.runs  # noqa: F401


@contextmanager
def auth_phase(session: Session, tenant_id: str) -> Iterator[Session]:
    """Temporarily allow identity-table writes (users, invitations) from a tenant-scoped request, then re-bind the tenant.
    Only tenant-admin user management uses this; every use is audited by its caller."""
    begin_auth_lookup(session)
    try:
        yield session
    finally:
        session.flush()
        bind_tenant(session, tenant_id)
