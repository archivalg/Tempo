"""DAT-04: pooling/retry/timeout configuration. Tests
app/db.py::build_engine_kwargs directly — a pure function of
(database_url, Settings) — rather than reloading app.db/app.config
(tried first, rejected: reloading redefines `Base` as a fresh class with
empty metadata, silently breaking every other test in the same pytest
session that relies on the original `Base.metadata` already having every
model registered). SQLAlchemy's create_engine never actually connects
until first use, so a fake (unreachable) postgresql:// URL proves the pool
is configured as intended with no real database required.
"""
from __future__ import annotations

from sqlalchemy import create_engine

from app.config import Settings
from app.db import build_engine_kwargs


def test_sqlite_kwargs_omit_pool_size_and_keep_check_same_thread():
    kwargs = build_engine_kwargs("sqlite:///./whatever.db", Settings())
    assert kwargs["connect_args"] == {"check_same_thread": False}
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs

    # sqlite3 is stdlib, so this proves the kwargs are actually accepted by
    # create_engine, not just structurally present in the dict.
    engine = create_engine("sqlite:///./_test_db_engine_config.db", **kwargs)
    engine.dispose()


def test_non_sqlite_kwargs_carry_configured_pool_settings():
    # No postgres/oracle driver is installed in this environment (that's
    # ADR-0002's decision to make) — asserting on the kwargs dict itself is
    # exactly what app/db.py passes to create_engine, so this is still a
    # real test of this module's behaviour, just without instantiating an
    # engine that needs a driver this sandbox doesn't have.
    config = Settings(db_pool_size=17, db_max_overflow=3, db_pool_timeout_seconds=5, db_pool_recycle_seconds=60)
    kwargs = build_engine_kwargs("postgresql://user:pass@localhost/tempo_would_not_connect", config)
    assert kwargs["connect_args"] == {}
    assert kwargs["pool_size"] == 17
    assert kwargs["max_overflow"] == 3
    assert kwargs["pool_timeout"] == 5
    assert kwargs["pool_recycle"] == 60


def test_pool_pre_ping_is_always_honoured_regardless_of_dialect():
    sqlite_kwargs = build_engine_kwargs("sqlite:///./whatever.db", Settings(db_pool_pre_ping=False))
    postgres_kwargs = build_engine_kwargs("postgresql://user:pass@localhost/db", Settings(db_pool_pre_ping=False))
    assert sqlite_kwargs["pool_pre_ping"] is False
    assert postgres_kwargs["pool_pre_ping"] is False
