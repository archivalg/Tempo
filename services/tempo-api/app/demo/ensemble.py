"""bootstrap_ensemble_demo — the Ensemble Solutions internal proving environment.

EVERYTHING this creates is SYNTHETIC and labelled so (`is_synthetic`, numeric synthetic badge numbers,
"(synthetic)" names). Refuses to run when TEMPO_ENV=production. Idempotent and versioned: a second
run with the same manifest version is a no-op; `--reset` wipes the demo tenant (never audit rows,
which are append-only) and re-seeds anchored to the current time.

Honest by construction: the baseline roster, forecast, recommendation and scenarios come from the
real solvers driven through the real API (validate → execute → native publish), not from inserts.
The only direct inserts are source records a real system would ingest (workers, demand history,
attendance punches, cost rules, backlog). No PINs or device secrets are printed or stored in the
dataset; the demo kiosk enrolment code and three worker PINs are written to a mode-600 file
outside the repository (TEMPO_DEMO_SECRETS_DIR, default ~/.config/tempo-demo).
"""
from __future__ import annotations

import os
import random
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app import db as db_module
from app.config import settings
from app.core import auth, kiosk
from app.core.exceptions_engine import detect_exceptions
from app.db import Base, begin_auth_lookup, bind_tenant
from app.models.attendance import WorkerCredential
from app.models.canonical import (
    ActivityRoleZoneMap, AttendanceSession, Availability, DemandBucket, LabourCostRule, LabourProvider, OptimisationPolicy,
    SellRateContract, ShiftAssignment, SkillCertification, TenantScope, Worker, WorkerPerformanceProfile, WorkStandard, ZoneBacklog,
)
from app.models.connectors import MaestroConnection
from app.models.directory import Customer, DataSourceStatus, Site, WorkerPerson, Zone
from app.models.identity import (
    KioskDevice, Tenant, TempoUser, TenantMembership, UserCustomerGrant, UserRoleAssignment, UserSiteGrant, UserSession,
)

TENANT = "ensemble_solutions"
MANIFEST = {"name": "bootstrap_ensemble_demo", "version": "1.0.0"}
SITE_MEL, SITE_SYD = "mel_dc_01", "syd_dc_02"
MEL_TZ = "Australia/Melbourne"
POLICY = "ensemble_demo_v1"
DEMO_DOMAIN = "demo.tempo.invalid"
ACTIVITIES = {  # activity: (peak units/hour, seconds/unit, role, zone)
    "receiving": (160, 90, "receiver", "inbound"),
    "picking": (620, 45, "picker", "pick_a"),
    "packing": (480, 60, "packer", "pack"),
    "dispatch": (200, 75, "loader", "dispatch"),
}
EXTRA_PICK_ZONE = ("picking", "picker", "pick_b")
ZONES = [("inbound", "Inbound"), ("pick_a", "Pick A"), ("pick_b", "Pick B"), ("pack", "Pack"), ("dispatch", "Dispatch")]
CUSTOMERS = [("cust_alpha", "Alpha Retail (synthetic)", 0.5), ("cust_bravo", "Bravo Health (synthetic)", 0.3), ("cust_charlie", "Charlie Foods (synthetic)", 0.2)]
# synthetic pay rates by (employment_type, role) — placeholders, NOT workplace-agreement rates.
RATE = {"permanent": 34.0, "casual": 41.0, "labour_hire": 46.0}
ROLE_PREMIUM = {"receiver": 1.5, "picker": 0.0, "packer": 0.0, "loader": 1.0}
PERSONAS = {  # persona: (roles, sites)
    "tenant_admin": (["tenant_admin"], [SITE_MEL, SITE_SYD]),
    "ops_manager": (["operations_manager"], [SITE_MEL, SITE_SYD]),
    "planner": (["planner"], [SITE_MEL]),
    "supervisor": (["supervisor"], [SITE_MEL]),
    "executive": (["executive"], [SITE_MEL, SITE_SYD]),
    "analyst": (["analyst"], [SITE_MEL]),
}
FIRST = ["Ava", "Liam", "Mia", "Noah", "Zoe", "Ethan", "Ivy", "Lucas", "Ruby", "Oscar", "Chloe", "Jack", "Ella", "Leo", "Grace", "Max", "Nina", "Sam",
         "Tara", "Omar", "Priya", "Kai", "Mei", "Arjun", "Sofia", "Jai", "Lena", "Tom", "Yara", "Ben", "Anh", "Dev", "Isla", "Joel", "Kira", "Milo"]
LAST = ["Nguyen", "Smith", "Patel", "Kim", "Brown", "Singh", "Chen", "Wilson", "Taylor", "Martin", "Lee", "Walker", "Hall", "Young", "King", "Scott",
        "Green", "Baker", "Adams", "Nelson", "Hill", "Wong", "Ali", "Rossi", "Popov", "Costa", "Ng", "Jones", "Clark", "Lewis"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _guard() -> None:
    if settings.env == "production":
        raise RuntimeError("bootstrap_ensemble_demo refuses to run in production")


def status(db: Session) -> dict | None:
    begin_auth_lookup(db)
    t = db.get(Tenant, TENANT)
    return None if t is None else (t.feature_flags or {}).get("seed_manifest")


# --------------------------------------------------------------------------- reset
_APPEND_ONLY = {"demand_override", "notification", "roster_handoff", "security_audit_event", "audit_record", "event_record", "roster_event"}


def reset(db: Session) -> None:
    _guard()
    begin_auth_lookup(db)
    if db.get(Tenant, TENANT) is None:
        return
    persona_ids = [u.user_id for u in db.scalars(select(TempoUser).where(TempoUser.email.like(f"%@{DEMO_DOMAIN}")))]
    # also people invited into the demo tenant (and nowhere else, and not platform admins): they only exist because of it
    from app.models.identity import PlatformAdmin, UserInvitation
    members = {m.user_id for m in db.scalars(select(TenantMembership).where(TenantMembership.tenant_id == TENANT))}
    for uid in members - set(persona_ids):
        elsewhere = db.scalar(select(TenantMembership.tenant_id).where(TenantMembership.user_id == uid, TenantMembership.tenant_id != TENANT).limit(1))
        if elsewhere is None and db.get(PlatformAdmin, uid) is None:
            persona_ids.append(uid)
    if persona_ids:
        db.execute(delete(UserInvitation).where(UserInvitation.user_id.in_(persona_ids)))
        db.execute(delete(UserSession).where(UserSession.user_id.in_(persona_ids)))
    bind_tenant(db, TENANT)
    # overrides are never deleted (their history is evidence); a reset retires them so they cannot apply to the re-seeded tenant
    db.execute(text("UPDATE demand_override SET state = 'revoked', revoke_reason = 'demo reset' WHERE state = 'active'"))
    db.execute(text("UPDATE roster_handoff SET state = 'superseded' WHERE state IN ('pending', 'exported', 'unconfirmed')"))
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in _APPEND_ONLY or "tenant_id" not in table.c or table.name == "tenant":
            continue
        db.execute(table.delete().where(table.c.tenant_id == TENANT))
    begin_auth_lookup(db)
    if persona_ids:
        db.execute(delete(TempoUser).where(TempoUser.user_id.in_(persona_ids)))
    db.execute(delete(Tenant).where(Tenant.tenant_id == TENANT))
    db.commit()


# --------------------------------------------------------------------------- generators
def _intraday(hour: int) -> float:
    # smooth demand curve: quiet overnight, ramps from 05:00, peaks 10:00-15:00, tails off in the evening
    table = {0: .22, 1: .2, 2: .2, 3: .22, 4: .3, 5: .5, 6: .7, 7: .85, 8: .95, 9: 1.0, 10: 1.05, 11: 1.05, 12: .95, 13: 1.0, 14: 1.05,
             15: 1.0, 16: .9, 17: .8, 18: .7, 19: .6, 20: .5, 21: .42, 22: .33, 23: .27}
    return table[hour]


def _weekday(wd: int) -> float:
    return {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.0, 5: .9, 6: .85}[wd]  # deliberately mild weekly seasonality (see ledger: forecast limits)


def _persona_users(db: Session) -> dict[str, TempoUser]:
    users = {}
    for persona in PERSONAS:
        u = TempoUser(external_subject=f"dev|{persona}", email=f"{persona}@{DEMO_DOMAIN}", display_name=f"Demo {persona.replace('_', ' ').title()} (synthetic)")
        db.add(u)
        users[persona] = u
    db.flush()
    return users


def _mk_workers(db: Session, rnd: random.Random, provider_id: str) -> list[Worker]:
    plan = [("permanent", 34), ("casual", 22), ("labour_hire", 16)]
    roles_cycle = ["picker"] * 9 + ["packer"] * 6 + ["receiver"] * 3 + ["loader"] * 4
    workers: list[Worker] = []
    n = 0
    for etype, count in plan:
        for _ in range(count):
            n += 1
            role = roles_cycle[(n * 7) % len(roles_cycle)]
            w = Worker(worker_id=f"ens-mel-{n:04d}", tenant_id=TENANT, employment_type=etype, home_site=SITE_MEL, status="active",
                       source_system="tempo_native", source_ref=f"SYN-{n:04d}", provider_id=provider_id if etype == "labour_hire" else None)
            workers.append(w)
    db.add_all(workers)
    db.flush()
    now = _now()
    for i, w in enumerate(workers):
        role = roles_cycle[((i + 1) * 7) % len(roles_cycle)]
        name = f"{FIRST[(i * 5) % len(FIRST)]} {LAST[(i * 11) % len(LAST)]} (synthetic)"
        db.add(WorkerPerson(worker_id=w.worker_id, tenant_id=TENANT, display_name=name, employee_no=str(1001 + i), is_synthetic=True))  # numeric badge number (keypad-friendly)
        skills = {role}
        if i % 5 == 0 and role != "picker":
            skills.add("picker")  # multi-skilled cover
        if i % 6 == 0:
            skills.add("packer")
        for sk in skills:
            db.add(SkillCertification(tenant_id=TENANT, worker_id=w.worker_id, skill_code=sk, valid_from=now - timedelta(days=400)))
        db.add(WorkerPerformanceProfile(worker_id=w.worker_id, tenant_id=TENANT, cost_per_hour=str(RATE[w.employment_type]),
                                        productivity_index=round(0.9 + rnd.random() * 0.25, 2), reliability_index=round(0.85 + rnd.random() * 0.14, 2),
                                        is_mentor=(i % 17 == 0)))
        w.__dict__["_syn_role"] = role
    # forklift licences: two expiring inside 14 days, one already expired -> certification exceptions
    fl = [w for w in workers if w.__dict__.get("_syn_role") in ("loader", "receiver")][:6]
    for j, w in enumerate(fl):
        vt = [now + timedelta(days=6), now + timedelta(days=11), now - timedelta(days=3), now + timedelta(days=240), now + timedelta(days=300), now + timedelta(days=400)][j]
        db.add(SkillCertification(tenant_id=TENANT, worker_id=w.worker_id, skill_code="forklift_lo", valid_from=now - timedelta(days=700), valid_to=vt, level="LO"))
    return workers


def _seed_demand(db: Session, rnd: random.Random, now: datetime, tz: ZoneInfo) -> None:
    week_start = (now.astimezone(tz) - timedelta(days=now.astimezone(tz).weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (week_start - timedelta(days=28)).astimezone(timezone.utc)
    end_hour = now.replace(minute=0, second=0, microsecond=0)
    rows, daily = [], defaultdict(lambda: defaultdict(float))
    h = start
    while h <= end_hour:
        loc = h.astimezone(tz)
        for act, (peak, _sec, _r, _z) in ACTIVITIES.items():
            vol = peak * _intraday(loc.hour) * _weekday(loc.weekday()) * (1 + 0.004 * ((h - start).days)) * (1 + rnd.uniform(-0.08, 0.08))
            for cid, _n, share in CUSTOMERS:
                rows.append({"id": str(uuid.uuid4()), "tenant_id": TENANT, "activity": act, "site_id": SITE_MEL, "customer_id": cid, "interval_start": h,
                             "volume": round(vol * share, 1), "source": "synthetic_demo", "bucket_minutes": 60})
            if h < week_start.astimezone(timezone.utc) or h.astimezone(tz).date() < now.astimezone(tz).date():
                daily[(loc.date(), act)]["v"] += vol
        h += timedelta(hours=1)
    for (d, act), v in daily.items():
        midnight = datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(timezone.utc)
        rows.append({"id": str(uuid.uuid4()), "tenant_id": TENANT, "activity": act, "site_id": SITE_MEL, "customer_id": None, "interval_start": midnight,
                     "volume": round(v["v"], 1), "source": "synthetic_demo", "bucket_minutes": 1440})
    db.execute(DemandBucket.__table__.insert(), rows)


def _config(db: Session, now: datetime) -> None:
    for act, (_p, sec, role, zone) in ACTIVITIES.items():
        db.add(WorkStandard(tenant_id=TENANT, activity=act, time_per_unit_seconds=float(sec), effective_from=now - timedelta(days=800)))
        db.add(ActivityRoleZoneMap(tenant_id=TENANT, site_id=SITE_MEL, activity=act, role=role, zone=zone, weight=1.0))
    act, role, zone = EXTRA_PICK_ZONE
    db.add(ActivityRoleZoneMap(tenant_id=TENANT, site_id=SITE_MEL, activity=act, role=role, zone=zone, weight=1.0))
    for etype, base in RATE.items():
        for role, prem in ROLE_PREMIUM.items():
            db.add(LabourCostRule(tenant_id=TENANT, labour_type=etype, role=role, rate=f"{base + prem:.2f}", overtime_multiplier="1.5",
                                  surcharge="8.00" if etype == "labour_hire" else None, currency="AUD"))
    db.add(OptimisationPolicy(policy_version=POLICY, tenant_id=TENANT, jurisdiction="AU-VIC", constraints={
        "shift_calendar": [{"code": "early", "start_hour": 6, "end_hour": 14, "share": 0.48}, {"code": "late", "start_hour": 14, "end_hour": 22, "share": 0.38},
                           {"code": "night", "start_hour": 22, "end_hour": 6, "share": 0.14}],
        "hours_per_worker_per_day": 8.0, "internal_min_ratio": 0.6, "hire_max_ratio": 0.4, "max_consecutive_days": 5}))
    for cid, _n, _s in CUSTOMERS:
        for act in ACTIVITIES:
            db.add(SellRateContract(tenant_id=TENANT, customer_id=cid, activity=act, rate="0.95", currency="AUD", effective_from=now - timedelta(days=500)))


# --------------------------------------------------------------------------- orchestration
def bootstrap(*, reset_first: bool = False, secrets_dir: str | None = None) -> dict:
    _guard()
    from fastapi.testclient import TestClient

    from app.main import app

    db = db_module.SessionLocal()
    try:
        existing = status(db)
        if existing and not reset_first:
            return {"result": "already_seeded", "manifest": existing}
        begin_auth_lookup(db)
        if db.get(Tenant, TENANT) is not None:  # a completed seed being reset, or a half-finished one being recovered
            reset(db)
            db.close()
            db = db_module.SessionLocal()
        now = _now()
        tz = ZoneInfo(MEL_TZ)
        rnd = random.Random(20260930)

        # identity + tenant (auth phase)
        begin_auth_lookup(db)
        db.add(Tenant(tenant_id=TENANT, name="Ensemble Solutions", plan="internal-proving", created_by="bootstrap_ensemble_demo"))
        db.flush()
        users = _persona_users(db)
        bind_tenant(db, TENANT)
        for persona, (roles, sites) in PERSONAS.items():
            u = users[persona]
            db.add(TenantMembership(user_id=u.user_id, tenant_id=TENANT, is_default=True, invitation_source="bootstrap_ensemble_demo"))
            for r in roles:
                db.add(UserRoleAssignment(user_id=u.user_id, tenant_id=TENANT, role=r))
            for s in sites:
                db.add(UserSiteGrant(user_id=u.user_id, tenant_id=TENANT, site_id=s))
            for cid, _n, _sh in CUSTOMERS:
                db.add(UserCustomerGrant(user_id=u.user_id, tenant_id=TENANT, customer_id=cid))

        # directory
        db.add(Site(tenant_id=TENANT, site_id=SITE_MEL, name="Melbourne DC (synthetic)", timezone=MEL_TZ, operating_mode="standalone", is_synthetic=True))
        db.add(Site(tenant_id=TENANT, site_id=SITE_SYD, name="Sydney DC (synthetic, Overlay demo)", timezone="Australia/Sydney", operating_mode="overlay", is_synthetic=True))
        for cid, name, _s in CUSTOMERS:
            db.add(Customer(tenant_id=TENANT, customer_id=cid, name=name))
            db.add(TenantScope(tenant_id=TENANT, site_id=SITE_MEL, company_id="ensemble", customer_id=cid) if cid == "cust_alpha" else TenantScope(
                tenant_id=TENANT, site_id=f"{SITE_MEL}:{cid}", company_id="ensemble", customer_id=cid))
        db.add(TenantScope(tenant_id=TENANT, site_id=SITE_SYD, company_id="ensemble"))
        for i, (zid, zname) in enumerate(ZONES):
            db.add(Zone(tenant_id=TENANT, site_id=SITE_MEL, zone_id=zid, name=zname, sort_order=i))
        for i, (zid, zname) in enumerate([("inbound", "Inbound"), ("pick", "Pick"), ("pack", "Pack")]):
            db.add(Zone(tenant_id=TENANT, site_id=SITE_SYD, zone_id=zid, name=zname, sort_order=i))
        prov = LabourProvider(tenant_id=TENANT, name="Synthetic Labour Hire Co")
        db.add(prov)
        db.flush()
        workers = _mk_workers(db, rnd, prov.provider_id)
        _config(db, now)
        _seed_demand(db, rnd, now, tz)
        db.flush()

        # kiosk + operator secrets (outside the repo)
        dev = KioskDevice(tenant_id=TENANT, site_ids=[SITE_MEL], name="Melbourne DC — Dock 1 (demo kiosk)", created_by="bootstrap_ensemble_demo")
        db.add(dev)
        db.flush()
        code = kiosk.new_enrolment_code(dev)
        pins = {}
        for n, w in enumerate(workers[:3]):
            pin = f"{secrets.randbelow(10**6):06d}"
            db.add(WorkerCredential(worker_id=w.worker_id, tenant_id=TENANT, pin_hash=kiosk.hash_pin(pin)))
            pins[str(1001 + n)] = pin
        sd = Path(secrets_dir or os.environ.get("TEMPO_DEMO_SECRETS_DIR") or Path.home() / ".config" / "tempo-demo")
        sd.mkdir(parents=True, exist_ok=True)
        os.chmod(sd, 0o700)
        f = sd / "kiosk.txt"
        f.write_text("# Ensemble demo kiosk — SYNTHETIC. Enrolment code expires in 15 minutes; PINs are for the 3 workers listed.\n"
                     f"enrolment_code={code}\n" + "".join(f"worker_no={k} pin={v}\n" for k, v in pins.items()))
        os.chmod(f, 0o600)

        # Sydney (Overlay, simulated + stale)
        _seed_sydney(db, rnd, now)
        db.commit()

        # run the real pipeline through the real API as the demo personas
        begin_auth_lookup(db)
        tokens = {}
        for persona, u in users.items():
            tokens[persona] = auth.create_session(db, u, mfa=True, auth_method="bootstrap").access_token
        db.commit()
        client = TestClient(app)
        _drive_pipeline(client, tokens, now, tz)

        # attendance + freshness + exceptions
        db2 = db_module.SessionLocal()
        try:
            bind_tenant(db2, TENANT)
            att = _seed_attendance(db2, rnd, now)
            _seed_pending_correction(db2, now)
            db2.add(DataSourceStatus(tenant_id=TENANT, site_id=SITE_MEL, source_key="attendance", label="Tempo kiosk attendance", kind="native", mode="live",
                                     last_success_at=now, stale_after_seconds=6 * 3600, note="Tempo-native capture. Demo punches are synthetic; freshness = seed time (re-run bootstrap to refresh)."))
            db2.add(DataSourceStatus(tenant_id=TENANT, site_id=SITE_MEL, source_key="demand", label="Demand history", kind="connector", mode="simulated",
                                     last_success_at=now, stale_after_seconds=6 * 3600, note="Synthetic demand generated by bootstrap_ensemble_demo. No WMS is connected."))
            db2.add(DataSourceStatus(tenant_id=TENANT, site_id=SITE_MEL, source_key="roster", label="Tempo roster", kind="native", mode="live",
                                     last_success_at=now, stale_after_seconds=24 * 3600, note="Roster of record is Tempo (Standalone)."))
            db2.flush()
            cases = {SITE_MEL: detect_exceptions(db2, TENANT, SITE_MEL, now), SITE_SYD: detect_exceptions(db2, TENANT, SITE_SYD, now)}
            manifest = {**MANIFEST, "seeded_at": now.isoformat(), "synthetic": True, "counts": {"workers_mel": len(workers), "attendance": att, "exceptions": cases},
                        "secrets_file": str(f)}
            begin_auth_lookup(db2)
            t = db2.get(Tenant, TENANT)
            t.feature_flags = {**(t.feature_flags or {}), "seed_manifest": manifest, "synthetic": True}
            db2.commit()
        finally:
            db2.close()
        return {"result": "seeded", "manifest": manifest}
    finally:
        db.close()


def _seed_sydney(db: Session, rnd: random.Random, now: datetime) -> None:
    ws = []
    for i in range(14):
        w = Worker(worker_id=f"ens-syd-{i + 1:04d}", tenant_id=TENANT, employment_type="permanent" if i < 9 else "casual", home_site=SITE_SYD,
                   status="active", source_system="deputy_simulated", source_ref=f"SYN-SYD-{i + 1:04d}")
        ws.append(w)
    db.add_all(ws)
    db.flush()
    tz = ZoneInfo("Australia/Sydney")
    today = now.astimezone(tz).date()
    for i, w in enumerate(ws):
        db.add(WorkerPerson(worker_id=w.worker_id, tenant_id=TENANT, display_name=f"{FIRST[(i * 3 + 2) % len(FIRST)]} {LAST[(i * 7 + 3) % len(LAST)]} (synthetic)",
                            employee_no=str(2001 + i), is_synthetic=True))
        db.add(SkillCertification(tenant_id=TENANT, worker_id=w.worker_id, skill_code="picker", valid_from=now - timedelta(days=300)))
        for d in range(0, 5):
            day = today + timedelta(days=d - today.weekday() if d - today.weekday() >= -6 else d)
        for d in range(7):
            dd = today - timedelta(days=today.weekday()) + timedelta(days=d)
            if (i + d) % 3 == 2:
                continue
            start = datetime(dd.year, dd.month, dd.day, 7 if i % 2 == 0 else 15, tzinfo=tz).astimezone(timezone.utc)
            db.add(ShiftAssignment(tenant_id=TENANT, worker_id=w.worker_id, role="picker", zone="pick", start_at=start, end_at=start + timedelta(hours=8),
                                   status="committed", source_system="deputy_simulated", source_ref=f"dep-sim-{i}-{d}"))
    db.add(MaestroConnection(tenant_id=TENANT, source_system="deputy", site_id=SITE_SYD, display_name="Deputy — SIMULATED (no vendor credentials, no live sync)",
                             status="pending_credentials"))
    db.add(DataSourceStatus(tenant_id=TENANT, site_id=SITE_SYD, source_key="attendance", label="Deputy timesheets (SIMULATED connector)", kind="connector",
                            mode="stale", last_success_at=now - timedelta(hours=3), stale_after_seconds=900,
                            note="Simulated Overlay connector: last 'sync' was 3h ago and has failed since. Not connected to any vendor."))
    db.add(DataSourceStatus(tenant_id=TENANT, site_id=SITE_SYD, source_key="roster", label="Deputy roster (SIMULATED connector)", kind="connector", mode="simulated",
                            last_success_at=now - timedelta(hours=3), stale_after_seconds=900, note="Simulated roster snapshot; source of truth is the vendor system."))
    # an attendance punch that pre-dates the failure, so 'present' looks plausible but must not be trusted
    for i, w in enumerate(ws[:6]):
        db.add(AttendanceSession(tenant_id=TENANT, worker_id=w.worker_id, start_at=now - timedelta(hours=4, minutes=rnd.randint(0, 20)), end_at=None,
                                 approval="pending", source_system="deputy_simulated", source_ref="dep-sim-punch"))


def _drive_pipeline(client, tokens: dict[str, str], now: datetime, tz: ZoneInfo) -> None:
    """Forecast → requirement → mix → named roster → approve → native publish → intraday → scenario, all via the API."""
    def h(persona, key=None):
        return {"Authorization": f"Bearer {tokens[persona]}", "Idempotency-Key": key or str(uuid.uuid4())}

    week_start = (now.astimezone(tz) - timedelta(days=now.astimezone(tz).weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    body = lambda kind, start, end, bucket: {  # noqa: E731
        "request_id": f"req_{kind}_{uuid.uuid4().hex[:8]}",
        "scope": {"tenant_id": TENANT, "site_ids": [SITE_MEL], "customer_ids": [c[0] for c in CUSTOMERS]},
        "planning_window": {"start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "timezone": MEL_TZ, "bucket_minutes": bucket},
        "configuration": {"policy_version": POLICY}}
    wk = body("week", week_start, week_start + timedelta(days=7), 1440)
    steps = ["demand_forecast", "labour_requirement", "workforce_mix"]
    for rt in steps:
        r = client.post(f"/v1/optimisations/{rt}", json={**wk, "request_id": f"req_{rt}_{uuid.uuid4().hex[:8]}"}, headers=h("planner"))
        if r.status_code != 202:
            raise RuntimeError(f"{rt} failed: {r.status_code} {r.text[:300]}")
    # the roster goes through the real version workflow: generate -> submit (planner) -> approve (a different user) -> publish -> reconcile
    week_iso = week_start.date().isoformat()
    g = client.post(f"/v1/sites/{SITE_MEL}/rosters/generate", json={"week_start": week_iso, "policy_version": POLICY}, headers=h("planner"))
    if g.status_code != 201:
        raise RuntimeError(f"roster generate failed: {g.status_code} {g.text[:300]}")
    vid = g.json()["version"]["id"]
    if g.json()["hard_conflicts"]:
        raise RuntimeError(f"generated roster has {g.json()['hard_conflicts']} hard conflicts: {g.json()['conflicts'][:3]}")
    for step, persona, payload in (("submit", "planner", None), ("approve", "ops_manager", {"note": "Baseline roster for the proving environment (synthetic)."})):
        r = client.post(f"/v1/rosters/{vid}/{step}", json=payload, headers=h(persona)) if payload else client.post(f"/v1/rosters/{vid}/{step}", headers=h(persona))
        if r.status_code != 200:
            raise RuntimeError(f"roster {step} failed: {r.status_code} {r.text[:300]}")
    r = client.post(f"/v1/rosters/{vid}/publish", headers=h("ops_manager"))
    if r.status_code != 200 or r.json().get("state") != "reconciled":
        raise RuntimeError(f"publish failed: {r.status_code} {r.text[:300]}")

    # a backlog surge in Pick B while Pick A has slack -> real intraday recommendation
    from app.db import SessionLocal

    d = SessionLocal()
    try:
        bind_tenant(d, TENANT)
        hr = now.replace(minute=0, second=0, microsecond=0)
        d.add(ZoneBacklog(tenant_id=TENANT, site_id=SITE_MEL, zone="pick_b", interval_start=hr, backlog_units=9, source_system="simulated_wms"))
        d.add(ZoneBacklog(tenant_id=TENANT, site_id=SITE_MEL, zone="pick_a", interval_start=hr, backlog_units=1, source_system="simulated_wms"))
        d.commit()
    finally:
        d.close()
    hr = now.replace(minute=0, second=0, microsecond=0)
    ib = body("intraday", hr, hr + timedelta(hours=1), 60)
    r = client.post("/v1/optimisations/intraday_reallocation", json=ib, headers=h("ops_manager"))
    # An intraday run needs an active shift + backlog at this hour; when none exists (e.g. run at a quiet hour) the
    # dataset simply has no recommendation - we do not fabricate one.
    _ = r
    r = client.post("/v1/optimisations/scenario", json={**wk, "request_id": f"req_scn_{uuid.uuid4().hex[:8]}"}, headers=h("ops_manager"))
    _ = r


def _seed_attendance(db: Session, rnd: random.Random, now: datetime) -> dict:
    ws = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == TENANT, Worker.home_site == SITE_MEL))}
    shifts = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == TENANT, ShiftAssignment.worker_id.in_(list(ws)),
                                                      ShiftAssignment.status == "committed", ShiftAssignment.start_at < now)).all()
    made = {"sessions": 0, "late": 0, "no_show": 0, "early_departure": 0, "unrostered": 0, "missing_punch_out": 0}
    missing_done = False
    for sh in sorted(shifts, key=lambda s: s.start_at):
        st, en = sh.start_at, sh.end_at
        if st.tzinfo is None:
            st, en = st.replace(tzinfo=timezone.utc), en.replace(tzinfo=timezone.utc)
        roll = rnd.random()
        recent = now - st < timedelta(hours=16)
        if roll < 0.035 and recent and now > st + timedelta(minutes=25):
            made["no_show"] += 1
            continue
        delay = timedelta(minutes=rnd.randint(-6, 4))
        if roll < 0.10:
            delay = timedelta(minutes=rnd.randint(13, 40))
            made["late"] += 1
        pin = st + delay
        if pin > now - timedelta(minutes=1):
            continue  # a punch can't be in the future: this worker simply hasn't arrived yet
        pout = None
        if en < now:
            pout = en + timedelta(minutes=rnd.randint(0, 8))
            if 0.10 <= roll < 0.125:
                pout = en - timedelta(minutes=rnd.randint(45, 90))
                made["early_departure"] += 1
            elif not missing_done and now - en > timedelta(hours=3) and now - en < timedelta(hours=14) and roll > 0.97:
                pout, missing_done = None, True
                made["missing_punch_out"] += 1
        db.add(AttendanceSession(tenant_id=TENANT, worker_id=sh.worker_id, start_at=pin, end_at=pout, breaks_minutes=30 if pout else 0,
                                 approval="approved" if (pout and now - en > timedelta(hours=20)) else "pending", pay_code="ORD",
                                 source_system="tempo_native", source_ref="synthetic-seed"))
        made["sessions"] += 1
    active = {sh.worker_id for sh in shifts if (sh.start_at.replace(tzinfo=timezone.utc) if sh.start_at.tzinfo is None else sh.start_at) - timedelta(hours=1) <= now
              < (sh.end_at.replace(tzinfo=timezone.utc) if sh.end_at.tzinfo is None else sh.end_at) + timedelta(hours=1)}
    spare = [w for wid, w in sorted(ws.items()) if wid not in active]
    if spare:
        db.add(AttendanceSession(tenant_id=TENANT, worker_id=spare[-1].worker_id, start_at=now - timedelta(minutes=22), end_at=None, approval="pending",
                                 source_system="tempo_native", source_ref="synthetic-seed-unrostered"))
        made["unrostered"] += 1
    db.flush()
    return made


def _seed_pending_correction(db: Session, now: datetime) -> None:
    """One supervised correction awaiting a second person's approval (the original punch stays untouched)."""
    from app.models.rosters import AttendanceAdjustment

    sup = db.scalar(select(TempoUser).where(TempoUser.email == f"supervisor@{DEMO_DOMAIN}"))
    x = db.scalar(select(AttendanceSession).where(AttendanceSession.tenant_id == TENANT, AttendanceSession.end_at.is_not(None),
                                                  AttendanceSession.source_ref == "synthetic-seed", AttendanceSession.approval == "pending").order_by(AttendanceSession.start_at.desc()).limit(1))
    if x is not None and sup is not None:
        end = x.end_at if x.end_at.tzinfo else x.end_at.replace(tzinfo=timezone.utc)
        db.add(AttendanceAdjustment(tenant_id=TENANT, session_id=x.id, site_id=SITE_MEL, requested_start=x.start_at, requested_end=end + timedelta(minutes=25),
                                    reason="Worker stayed to complete a dock unload; supervisor witnessed (synthetic).", requested_by=sup.user_id))
