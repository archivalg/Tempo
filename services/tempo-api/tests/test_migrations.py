"""DAT-02: "Replace automatic create-all schema management with versioned
Alembic migrations" — acceptance criterion "the previous supported release
can be upgraded without data loss" and "a clean environment can be created
solely through migrations." This test drives Alembic's own Python API
(not a shell-out) against a throwaway SQLite file, proving upgrade head
and downgrade base both work cleanly — the same property a real Oracle
environment needs, checked here without needing one (ADR-0002).
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(db_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def test_upgrade_head_creates_every_application_table(tmp_path):
    db_path = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_path}"

    command.upgrade(_alembic_config(db_url), "head")

    inspector = inspect(create_engine(db_url))
    tables = set(inspector.get_table_names())
    assert "alembic_version" in tables
    # Spot-check tables from every model module Alembic's env.py imports —
    # a real regression here would mean env.py stopped seeing one of them.
    for expected in (
        "optimisation_run",
        "optimisation_run_site",
        "optimisation_run_customer",
        "optimisation_snapshot",
        "action_request",
        "worker",
        "labour_provider",
        "tempo_user",
        "tenant_membership",
        "user_site_grant",
        "security_audit_event",
        "maestro_connection",
        "worker_credential",
    ):
        assert expected in tables, f"expected table '{expected}' missing after upgrade head"


def test_downgrade_base_leaves_only_alembic_bookkeeping(tmp_path):
    db_path = tmp_path / "migration_downgrade_test.db"
    db_url = f"sqlite:///{db_path}"
    config = _alembic_config(db_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    inspector = inspect(create_engine(db_url))
    tables = set(inspector.get_table_names())
    assert tables == {"alembic_version"}
