"""DAT-02 on PostgreSQL (ADR-0011): a clean database is built solely through migrations,
and the migrations round-trip (upgrade head -> downgrade base -> upgrade head)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

REPO_ROOT = Path(__file__).resolve().parent.parent


def _cfg(owner_engine) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", owner_engine.url.render_as_string(hide_password=False))
    return config


def test_upgrade_head_creates_every_application_table(owner_engine):
    tables = set(inspect(owner_engine).get_table_names())
    assert "alembic_version" in tables
    for expected in (
        "optimisation_run", "optimisation_run_site", "optimisation_run_customer", "optimisation_snapshot",
        "action_request", "worker", "labour_provider", "tempo_user", "tenant_membership", "user_site_grant",
        "security_audit_event", "maestro_connection", "connector_credential_reference", "worker_credential",
        "platform_admin",
    ):
        assert expected in tables, f"expected table '{expected}' missing after upgrade head"


def test_downgrade_base_then_upgrade_round_trips(owner_engine):
    cfg = _cfg(owner_engine)
    try:
        command.downgrade(cfg, "base")
        assert set(inspect(owner_engine).get_table_names()) == {"alembic_version"}
    finally:
        command.upgrade(cfg, "head")
    with owner_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_class WHERE relrowsecurity")).scalar() >= 40
