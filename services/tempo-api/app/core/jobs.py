"""The notification job loop: reminders, pushes, retries and receipts for every tenant.

There is no separate worker process in Tempo, so the API process can run this loop (TEMPO_JOBS_ENABLED=true). It takes a Postgres advisory lock for each
cycle, so two API instances never process the same jobs; a job is also unique per (tenant, key), so even a double run cannot send twice.
`python -m app.cli run-notification-jobs` runs one cycle by hand.
"""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import select, text

from app import db as db_module
from app.config import settings
from app.core import push
from app.db import begin_auth_lookup, bind_tenant
from app.models.identity import Tenant

log = logging.getLogger("tempo.jobs")
LOCK_KEY = 7_420_001


def run_cycle() -> dict:
    """One pass over all active tenants. Returns a summary; never raises (a failing tenant is logged and skipped)."""
    db = db_module.SessionLocal()
    summary: dict = {"tenants": 0, "processed": 0, "skipped": False}
    try:
        got = db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
        if not got:
            summary["skipped"] = True
            return summary
        try:
            begin_auth_lookup(db)
            tenants = [t for t in db.scalars(select(Tenant.tenant_id).where(Tenant.status == "active"))]
            db.commit()
            for tid in tenants:
                try:
                    bind_tenant(db, tid)
                    r = push.process_due(db, tid)
                    db.commit()
                    summary["tenants"] += 1
                    summary["processed"] += r["processed"]
                except Exception:  # noqa: BLE001
                    db.rollback()
                    log.exception("notification jobs failed for tenant %s", tid)
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            db.commit()
    finally:
        db.close()
    return summary


def start_background_loop() -> threading.Thread | None:
    if not settings.jobs_enabled:
        return None

    def loop() -> None:
        while True:
            try:
                run_cycle()
            except Exception:  # noqa: BLE001
                log.exception("job cycle failed")
            time.sleep(max(5, settings.jobs_interval_seconds))

    t = threading.Thread(target=loop, name="tempo-notification-jobs", daemon=True)
    t.start()
    return t
