"""Seeds a clean, deterministic dataset for services/tempo-console's
Playwright E2E suite — not part of the application itself, a dev/test
utility invoked by tempo-console/playwright.config.ts's webServer command
before each E2E run.

Always drops and recreates the schema first, so every run starts from an
identical, known state (the suite asserts against specific values this
script seeds, e.g. an exact worker count) — the same reason
app/api/v1/runs.py's capacity tests seed their own fixture rather than
relying on whatever happens to be in a shared dev database.

Reuses tests/factories.py's seed_named_roster_scenario rather than
duplicating it — this script only adds what that fixture doesn't already
cover: a clock-in credential (Kiosk) and a committed ShiftAssignment
(Team Attendance's "matches a rostered shift" case).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.attendance import hash_pin  # noqa: E402
from app.db import Base, engine, SessionLocal  # noqa: E402
from app.models.attendance import WorkerCredential  # noqa: E402
from app.models.canonical import ShiftAssignment  # noqa: E402
from tests.factories import seed_named_roster_scenario  # noqa: E402

TENANT_ID = "ten_e2e"
SITE_ID = "site_e2e_01"
KIOSK_WORKER_ID = "wrk_0"  # first worker seed_named_roster_scenario creates
KIOSK_PIN = "1234"


def _today_utc_midnight() -> datetime:
    # Matches services/tempo-console's NewRun page default window (today ->
    # +7 days) so a run created with the console's own defaults lines up
    # with this seeded demand history without the test needing to know
    # the console's date-picker internals.
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def main() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    window_start = _today_utc_midnight()
    db = SessionLocal()
    try:
        seed_named_roster_scenario(db, tenant_id=TENANT_ID, site_id=SITE_ID, window_start=window_start)

        db.add(WorkerCredential(worker_id=KIOSK_WORKER_ID, tenant_id=TENANT_ID, pin_hash=hash_pin(KIOSK_PIN)))
        db.add(
            ShiftAssignment(
                tenant_id=TENANT_ID,
                worker_id=KIOSK_WORKER_ID,
                role="picker",
                zone="zone_a",
                start_at=datetime.now(timezone.utc) - timedelta(hours=1),
                end_at=datetime.now(timezone.utc) + timedelta(hours=7),
                status="committed",
            )
        )
        db.commit()
    finally:
        db.close()

    print(f"seeded tenant '{TENANT_ID}' / site '{SITE_ID}' for E2E — kiosk worker '{KIOSK_WORKER_ID}', PIN {KIOSK_PIN}")


if __name__ == "__main__":
    main()
