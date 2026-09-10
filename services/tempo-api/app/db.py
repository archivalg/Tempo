from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import Settings, settings


def build_engine_kwargs(database_url: str, config: Settings) -> dict:
    """DAT-04: pooling/retry/timeout config, real only for a non-SQLite
    database — SQLite's default poolclass (NullPool) raises if given
    pool_size/max_overflow at all, so these are simply omitted for it
    rather than passed as values NullPool would reject. A pure function
    (no module-level engine/Base side effects) so tests/test_db_engine_config.py
    can exercise every branch directly, against a throwaway Settings
    instance, without touching this module's own global `engine` — reloading
    this module to test it was tried first and rejected: it re-defines
    `Base` as a new class with fresh (empty) metadata, silently breaking
    every other test in the same pytest session that relies on
    `Base.metadata` already having every model registered against it.
    """
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    kwargs: dict = {"connect_args": connect_args, "pool_pre_ping": config.db_pool_pre_ping}
    if not is_sqlite:
        kwargs.update(
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
            pool_timeout=config.db_pool_timeout_seconds,
            pool_recycle=config.db_pool_recycle_seconds,
        )
    return kwargs


_engine_kwargs = build_engine_kwargs(settings.database_url, settings)
connect_args = _engine_kwargs["connect_args"]
engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    # create_all is still fine here: this is the app's own dev-server
    # bootstrap and every test's per-run fixture (a fresh SQLite file each
    # time, no upgrade history to preserve). alembic/ (DAT-02) is now the
    # only path for a real environment — see that directory's env.py and
    # tests/test_migrations.py, which prove upgrade head / downgrade base
    # both work against this exact model set.
    import app.models.attendance  # noqa: F401
    import app.models.canonical  # noqa: F401
    import app.models.connectors  # noqa: F401
    import app.models.identity  # noqa: F401
    import app.models.runs  # noqa: F401

    Base.metadata.create_all(bind=engine)
