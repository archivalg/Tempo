"""Engine config is PostgreSQL-only (ADR-0011); pure-function tests, no connection needed."""
import pytest

from app.config import Settings
from app.db import build_engine_kwargs


def test_non_postgres_urls_are_refused():
    with pytest.raises(ValueError, match="PostgreSQL only"):
        build_engine_kwargs("sqlite:///./whatever.db", Settings())


def test_postgres_kwargs_carry_configured_pool_and_timeout_settings():
    config = Settings(db_pool_size=17, db_max_overflow=3, db_pool_timeout_seconds=5,
                      db_pool_recycle_seconds=60, db_statement_timeout_ms=1234)
    kwargs = build_engine_kwargs("postgresql+psycopg://u:p@localhost/db", config)
    assert (kwargs["pool_size"], kwargs["max_overflow"], kwargs["pool_timeout"], kwargs["pool_recycle"]) == (17, 3, 5, 60)
    assert kwargs["connect_args"] == {"options": "-c statement_timeout=1234"}


def test_pool_pre_ping_is_honoured():
    assert build_engine_kwargs("postgresql://u:p@h/db", Settings(db_pool_pre_ping=False))["pool_pre_ping"] is False
