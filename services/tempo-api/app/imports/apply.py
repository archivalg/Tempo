"""Applying and undoing a staged batch. Raw evidence stays; derived workload (`demand_bucket`) is written or rebuilt from it."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import auth, notifications as nt
from app.imports import validate as V
from app.imports.engine import BULK, TXN, _aware, _good, _now, _plan_events, lookups
from app.imports.parse import ImportProblem, local_day_bounds, parse_local_date
from app.models.canonical import DemandBucket, SkillCertification, Worker, WorkStandard
from app.models.directory import Customer, Site, WorkerPerson
from app.models.imports import ActualsPolicy, ImportBatch, ImportRow, SuppliedForecast, WorkloadEvent
from app.models.rosters import RosterEvent, RosterVersion
from app.schemas.tenancy import RequestContext

OPEN_ROSTER_STATES = ("draft", "pending_approval", "approved")


def _rows(db: Session, batch: ImportBatch) -> list[ImportRow]:
    return list(db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id).order_by(ImportRow.row_no)))


def _tz(db: Session, ctx: RequestContext) -> dict[str, ZoneInfo]:
    return {s.site_id: ZoneInfo(s.timezone) for s in db.scalars(select(Site).where(Site.tenant_id == ctx.tenant_id))}


# ------------------------------------------------------------------------------------------------------------------------- apply
def apply_batch(db: Session, ctx: RequestContext, batch: ImportBatch, *, accept_partial: bool = False) -> ImportBatch:
    if batch.tenant_id != ctx.tenant_id:
        raise ImportProblem("batch not found")
    if batch.state == "applied":
        return batch  # applying twice is a no-op, never a second write
    if batch.state != "validated":
        raise ImportProblem(f"this batch is {batch.state} and cannot be applied")
    blocking = (batch.summary or {}).get("blocking") or []
    if blocking:
        raise ImportProblem("this batch is held: " + " ".join(blocking))
    if batch.error_rows and not accept_partial:
        raise ImportProblem(f"{batch.error_rows} row(s) were rejected. Fix and re-upload the file, or choose to apply only the {batch.ok_rows + batch.warning_rows} accepted row(s).")
    if batch.ok_rows + batch.warning_rows == 0:
        raise ImportProblem("no rows were accepted, so there is nothing to apply")
    rows = _rows(db, batch)
    good = _good(rows)
    opts = (batch.summary or {}).get("options", {})
    result: dict
    dc = batch.data_class
    if dc == "master" and batch.entity == "workers":
        result = _apply_workers(db, ctx, good)
    elif dc == "master" and batch.entity in ("sites", "customers", "availability", "rates", "zones", "activity_roles", "operating_calendar", "shift_templates", "shift_breaks",
                                              "process_templates", "process_steps", "orders", "worker_activity_rates", "unit_conversions",
                                              "fill_priorities", "absenteeism", "equipment", "headcount_limits",
                                              "grade_rates", "productivity_loss", "staging_capacity", "staging_movements"):
        result = {"sites": _apply_sites, "customers": _apply_customers, "availability": _apply_availability, "rates": _apply_rates,
                  "zones": _apply_zones, "activity_roles": _apply_activity_roles, "operating_calendar": _apply_operating_calendar,
                  "shift_templates": _apply_shift_templates, "shift_breaks": _apply_shift_breaks,
                  "process_templates": _apply_process_templates, "process_steps": _apply_process_steps, "orders": _apply_orders,
                  "worker_activity_rates": _apply_worker_activity_rates, "unit_conversions": _apply_unit_conversions,
                  "fill_priorities": _apply_fill_priorities, "absenteeism": _apply_absenteeism, "equipment": _apply_equipment,
                  "headcount_limits": _apply_headcount_limits, "grade_rates": _apply_grade_rates, "productivity_loss": _apply_productivity_loss,
                  "staging_capacity": _apply_staging_capacity, "staging_movements": _apply_staging_movements}[batch.entity](db, ctx, batch, good)
    elif dc == "master":
        result = _apply_standards(db, ctx, good)
    elif dc == "forecast":
        result = _apply_forecast(db, ctx, batch, good, opts)
    elif dc == "transactions":
        result = _apply_transactions(db, ctx, batch, good, opts)
    else:
        result = _apply_bulk(db, ctx, batch, good, opts)
    batch.state, batch.applied_by, batch.applied_at = "applied", ctx.user_id, _now()
    batch.summary = {**(batch.summary or {}), "applied": result, "applied_partial": bool(batch.error_rows)}
    auth.audit(db, actor_type=("service" if ctx.user_id.startswith("svc:") else "user"), actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="import.apply", decision="allowed", reason_code=f"{dc}:rows={len(good)}", session_ref=batch.id, correlation_id=ctx.correlation_id)
    db.flush()
    return batch


def _apply_workers(db: Session, ctx: RequestContext, good: list[ImportRow]) -> dict:
    created = updated = 0
    for r in good:
        n = r.normalised
        w = db.scalar(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.source_system == "tempo_import", Worker.source_ref == n["worker_ref"]))
        if w is None:
            w = Worker(tenant_id=ctx.tenant_id, employment_type=n["employment_type"], home_site=n["site"], status=n["status"], source_system="tempo_import", source_ref=n["worker_ref"])
            db.add(w)
            db.flush()
            created += 1
        else:
            w.employment_type, w.home_site, w.status = n["employment_type"], n["site"], n["status"]
            updated += 1
        p = db.get(WorkerPerson, w.worker_id)
        if p is None:
            db.add(WorkerPerson(worker_id=w.worker_id, tenant_id=ctx.tenant_id, display_name=n["name"], employee_no=n.get("employee_no")))
        else:
            p.display_name, p.employee_no = n["name"], n.get("employee_no") or p.employee_no
        have = {c for c in db.scalars(select(SkillCertification.skill_code).where(SkillCertification.tenant_id == ctx.tenant_id, SkillCertification.worker_id == w.worker_id))}
        for code in n["skills"]:
            if code not in have:
                db.add(SkillCertification(tenant_id=ctx.tenant_id, worker_id=w.worker_id, skill_code=code, valid_from=_now()))
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_sites(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.db import bind_sites
    from app.models.identity import TempoUser, UserSiteGrant
    if not ctx.has_permission("labour.configure"):
        raise ImportProblem("adding or changing sites needs the configure permission")
    granted_user = db.get(TempoUser, ctx.user_id)
    created = updated = 0
    from app.core import subscription as _sub
    _sub.require_site_capacity(db, ctx.tenant_id, sum(1 for r in good if db.get(Site, (ctx.tenant_id, r.normalised["site_id"])) is None))
    db.execute(__import__('sqlalchemy').text("SELECT set_config('app.site_scope', '*', true)"))   # a new site is by definition outside the caller's current site scope; this path is gated by the permission above
    try:
        for r in good:
            n = r.normalised
            x = db.get(Site, (ctx.tenant_id, n["site_id"]))
            if x is None:
                db.add(Site(tenant_id=ctx.tenant_id, site_id=n["site_id"], name=n["name"], timezone=n["timezone"], operating_mode=n["operating_mode"]))
                if granted_user is not None:
                    db.flush()
                    db.add(UserSiteGrant(user_id=ctx.user_id, tenant_id=ctx.tenant_id, site_id=n["site_id"]))
                created += 1
            else:
                x.name, x.operating_mode = n["name"], n["operating_mode"]
                updated += 1
            r.applied = True
        db.flush()
    finally:
        bind_sites(db, list(ctx.site_ids) + [r.normalised["site_id"] for r in good if r.applied])
    return {"created": created, "updated": updated}


def _apply_customers(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    created = updated = 0
    for r in good:
        n = r.normalised
        c = db.get(Customer, (ctx.tenant_id, n["customer_id"]))
        if c is None:
            db.add(Customer(tenant_id=ctx.tenant_id, customer_id=n["customer_id"], name=n["name"], status=n["status"]))
            created += 1
        else:
            c.name, c.status = n["name"], n["status"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_rates(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.canonical import LabourCostRule
    created = updated = same = 0
    for r in good:
        n = r.normalised
        c = db.scalar(select(LabourCostRule).where(LabourCostRule.tenant_id == ctx.tenant_id, LabourCostRule.labour_type == n["employment_type"], LabourCostRule.role == n["role"]))
        vals = dict(rate=f"{n['hourly_rate']:.2f}", overtime_multiplier=None if n["overtime_multiplier"] is None else f"{n['overtime_multiplier']:g}", surcharge=None if n["surcharge"] is None else f"{n['surcharge']:.2f}")
        if c is None:
            db.add(LabourCostRule(tenant_id=ctx.tenant_id, labour_type=n["employment_type"], role=n["role"], **vals))
            created += 1
        elif (c.rate, c.overtime_multiplier, c.surcharge) == (vals["rate"], vals["overtime_multiplier"], vals["surcharge"]):
            same += 1
            continue
        else:
            for k, v in vals.items():
                setattr(c, k, v)
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated, "unchanged": same}


def _apply_zones(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.directory import Zone
    created = updated = 0
    for r in good:
        n = r.normalised
        z = db.get(Zone, (ctx.tenant_id, n["site"], n["zone_id"]))
        if z is None:
            db.add(Zone(tenant_id=ctx.tenant_id, site_id=n["site"], zone_id=n["zone_id"], name=n["zone_name"]))
            created += 1
        else:
            z.name = n["zone_name"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_activity_roles(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.canonical import ActivityRoleZoneMap
    created = updated = 0
    for r in good:
        n = r.normalised
        m = db.scalar(select(ActivityRoleZoneMap).where(ActivityRoleZoneMap.tenant_id == ctx.tenant_id, ActivityRoleZoneMap.site_id == n["site"],
                                                        ActivityRoleZoneMap.activity == n["activity"], ActivityRoleZoneMap.role == n["role"], ActivityRoleZoneMap.zone == n["zone_id"]))
        if m is None:
            db.add(ActivityRoleZoneMap(tenant_id=ctx.tenant_id, site_id=n["site"], activity=n["activity"], role=n["role"], zone=n["zone_id"], weight=n["weight"]))
            created += 1
        else:
            m.weight = n["weight"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_operating_calendar(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.scheduling import OperatingCalendarDay
    created = updated = 0
    for r in good:
        n = r.normalised
        c = db.scalar(select(OperatingCalendarDay).where(OperatingCalendarDay.tenant_id == ctx.tenant_id, OperatingCalendarDay.site_id == n["site"], OperatingCalendarDay.weekday == n["weekday"]))
        vals = dict(is_24h=n["is_24h"], is_closed=n["is_closed"], open_time=n["open_time"], close_time=n["close_time"])
        if c is None:
            db.add(OperatingCalendarDay(tenant_id=ctx.tenant_id, site_id=n["site"], weekday=n["weekday"], **vals))
            created += 1
        else:
            for k, v in vals.items():
                setattr(c, k, v)
            c.updated_at = _now()
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_shift_templates(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.scheduling import ShiftTemplate
    created = changed = same = 0
    for r in good:
        n = r.normalised
        start = parse_local_date(n["effective_from"])
        cur = db.scalar(select(ShiftTemplate).where(ShiftTemplate.tenant_id == ctx.tenant_id, ShiftTemplate.site_id == n["site"], ShiftTemplate.shift_code == n["shift_code"], ShiftTemplate.effective_to.is_(None)))
        if cur is not None and (cur.start_time, cur.end_time, cur.weekdays) == (n["start_time"], n["end_time"], n["weekdays"]):
            same += 1
            continue
        if cur is not None:
            if cur.effective_from >= start:
                cur.start_time, cur.end_time, cur.weekdays = n["start_time"], n["end_time"], n["weekdays"]  # same-day correction, no new row
                changed += 1
                r.applied = True
                continue
            cur.effective_to = start
            changed += 1
        else:
            created += 1
        db.add(ShiftTemplate(tenant_id=ctx.tenant_id, site_id=n["site"], shift_code=n["shift_code"], start_time=n["start_time"], end_time=n["end_time"], weekdays=n["weekdays"], effective_from=start))
        r.applied = True
    return {"created": created, "changed": changed, "unchanged": same}


def _apply_shift_breaks(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.scheduling import ShiftBreak, ShiftTemplate
    created = updated = same = 0
    for r in good:
        n = r.normalised
        tmpl = db.scalar(select(ShiftTemplate).where(ShiftTemplate.tenant_id == ctx.tenant_id, ShiftTemplate.site_id == n["site"], ShiftTemplate.shift_code == n["shift_code"], ShiftTemplate.effective_to.is_(None)))
        if tmpl is None:
            raise ImportProblem(f"shift_code '{n['shift_code']}' at site '{n['site']}' is no longer an active template")
        b = db.scalar(select(ShiftBreak).where(ShiftBreak.tenant_id == ctx.tenant_id, ShiftBreak.shift_template_id == tmpl.id,
                                               ShiftBreak.starts_after_minutes == n["starts_after_minutes"], ShiftBreak.duration_minutes == n["duration_minutes"]))
        if b is None:
            db.add(ShiftBreak(tenant_id=ctx.tenant_id, shift_template_id=tmpl.id, starts_after_minutes=n["starts_after_minutes"], duration_minutes=n["duration_minutes"], is_paid=n["is_paid"]))
            created += 1
        elif b.is_paid == n["is_paid"]:
            same += 1
            continue
        else:
            b.is_paid = n["is_paid"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated, "unchanged": same}


def _apply_process_templates(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.orders import ProcessTemplate
    created = updated = 0
    for r in good:
        n = r.normalised
        t = db.scalar(select(ProcessTemplate).where(ProcessTemplate.tenant_id == ctx.tenant_id, ProcessTemplate.site_id == n["site"],
                                                     ProcessTemplate.process_code == n["process_code"], ProcessTemplate.customer_id == n["customer_id"]))
        if t is None:
            db.add(ProcessTemplate(tenant_id=ctx.tenant_id, site_id=n["site"], process_code=n["process_code"], customer_id=n["customer_id"]))
            created += 1
        else:
            updated += 1  # nothing else to change — identity is the key itself
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_process_steps(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.orders import ProcessStep, ProcessTemplate
    created = updated = 0
    for r in good:
        n = r.normalised
        tmpl = db.scalar(select(ProcessTemplate).where(ProcessTemplate.tenant_id == ctx.tenant_id, ProcessTemplate.site_id == n["site"], ProcessTemplate.process_code == n["process_code"]))
        if tmpl is None:
            raise ImportProblem(f"process_code '{n['process_code']}' at site '{n['site']}' no longer exists")
        step = db.scalar(select(ProcessStep).where(ProcessStep.tenant_id == ctx.tenant_id, ProcessStep.process_template_id == tmpl.id, ProcessStep.sequence == n["sequence"]))
        if step is None:
            db.add(ProcessStep(tenant_id=ctx.tenant_id, process_template_id=tmpl.id, sequence=n["sequence"], activity=n["activity"], lag_minutes=n["lag_minutes"]))
            created += 1
        else:
            step.activity, step.lag_minutes = n["activity"], n["lag_minutes"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_orders(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.orders import Order, ProcessTemplate
    created = updated = 0
    for r in good:
        n = r.normalised
        tmpl = db.scalar(select(ProcessTemplate).where(ProcessTemplate.tenant_id == ctx.tenant_id, ProcessTemplate.site_id == n["site"], ProcessTemplate.process_code == n["process_code"]))
        if tmpl is None:
            raise ImportProblem(f"process_code '{n['process_code']}' at site '{n['site']}' no longer exists")
        o = db.scalar(select(Order).where(Order.tenant_id == ctx.tenant_id, Order.site_id == n["site"], Order.order_ref == n["order_id"]))
        vals = dict(customer_id=n["customer_id"], order_received=datetime.fromisoformat(n["order_received"]), despatch_due=datetime.fromisoformat(n["despatch_due"]),
                    units=n["units"], lines=n["lines"], unit=n["unit"], process_template_id=tmpl.id)
        if o is None:
            db.add(Order(tenant_id=ctx.tenant_id, site_id=n["site"], order_ref=n["order_id"], **vals))
            created += 1
        else:
            for k, v in vals.items():
                setattr(o, k, v)
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_worker_activity_rates(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.orders import WorkerActivityRate
    refs = {w.source_ref: w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.source_system == "tempo_import")) if w.source_ref}
    created = changed = same = 0
    for r in good:
        n = r.normalised
        wid, start = refs[n["worker_ref"]], parse_local_date(n["effective_from"])
        cur = db.scalar(select(WorkerActivityRate).where(WorkerActivityRate.tenant_id == ctx.tenant_id, WorkerActivityRate.worker_id == wid,
                                                         WorkerActivityRate.activity == n["activity"], WorkerActivityRate.effective_to.is_(None)))
        if cur is not None and abs(cur.rate_per_hour - n["rate_per_hour"]) < 1e-9 and cur.unit == n["unit"]:
            same += 1
            continue
        if cur is not None:
            if cur.effective_from >= start:
                cur.rate_per_hour, cur.unit = n["rate_per_hour"], n["unit"]  # same-day correction, no new row
                changed += 1
                r.applied = True
                continue
            cur.effective_to = start
            changed += 1
        else:
            created += 1
        db.add(WorkerActivityRate(tenant_id=ctx.tenant_id, worker_id=wid, activity=n["activity"], unit=n["unit"], rate_per_hour=n["rate_per_hour"], effective_from=start))
        r.applied = True
    return {"created": created, "changed": changed, "unchanged": same}


def _apply_unit_conversions(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.orders import UnitConversion
    created = updated = 0
    for r in good:
        n = r.normalised
        c = db.scalar(select(UnitConversion).where(UnitConversion.tenant_id == ctx.tenant_id, UnitConversion.activity == n.get("activity"),
                                                    UnitConversion.from_unit == n["from_unit"], UnitConversion.to_unit == n["to_unit"]))
        if c is None:
            db.add(UnitConversion(tenant_id=ctx.tenant_id, activity=n.get("activity"), from_unit=n["from_unit"], to_unit=n["to_unit"], factor=n["factor"]))
            created += 1
        else:
            c.factor = n["factor"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_fill_priorities(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.constraints import FillPriority
    created = updated = 0
    for r in good:
        n = r.normalised
        p = db.scalar(select(FillPriority).where(FillPriority.tenant_id == ctx.tenant_id, FillPriority.scope == n["scope"], FillPriority.value == n["value"]))
        if p is None:
            db.add(FillPriority(tenant_id=ctx.tenant_id, scope=n["scope"], value=n["value"], priority=n["priority"]))
            created += 1
        else:
            p.priority = n["priority"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_absenteeism(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.constraints import AbsenteeismRule
    created = updated = 0
    for r in good:
        n = r.normalised
        a = db.scalar(select(AbsenteeismRule).where(AbsenteeismRule.tenant_id == ctx.tenant_id, AbsenteeismRule.site_id == n["site"],
                                                     AbsenteeismRule.activity == n.get("activity"), AbsenteeismRule.weekday == n.get("weekday"), AbsenteeismRule.shift_code == n.get("shift_code")))
        if a is None:
            db.add(AbsenteeismRule(tenant_id=ctx.tenant_id, site_id=n["site"], activity=n.get("activity"), weekday=n.get("weekday"), shift_code=n.get("shift_code"), absence_pct=n["absence_pct"]))
            created += 1
        else:
            a.absence_pct = n["absence_pct"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_equipment(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.constraints import Equipment
    created = updated = 0
    for r in good:
        n = r.normalised
        e = db.scalar(select(Equipment).where(Equipment.tenant_id == ctx.tenant_id, Equipment.site_id == n["site"], Equipment.equipment_id == n["equipment_id"]))
        if e is None:
            db.add(Equipment(tenant_id=ctx.tenant_id, site_id=n["site"], equipment_id=n["equipment_id"], description=n["description"], quantity_available=n["quantity_available"]))
            created += 1
        else:
            e.description, e.quantity_available = n["description"], n["quantity_available"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_headcount_limits(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.constraints import HeadcountLimit
    created = updated = 0
    for r in good:
        n = r.normalised
        h = db.scalar(select(HeadcountLimit).where(HeadcountLimit.tenant_id == ctx.tenant_id, HeadcountLimit.site_id == n["site"],
                                                    HeadcountLimit.activity == n["activity"], HeadcountLimit.shift_code == n.get("shift_code")))
        if h is None:
            db.add(HeadcountLimit(tenant_id=ctx.tenant_id, site_id=n["site"], activity=n["activity"], shift_code=n.get("shift_code"), min_headcount=n["min_headcount"], max_headcount=n["max_headcount"]))
            created += 1
        else:
            h.min_headcount, h.max_headcount = n["min_headcount"], n["max_headcount"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_grade_rates(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.canonical import LabourCostRule
    created = updated = 0
    for r in good:
        n = r.normalised
        c = db.scalar(select(LabourCostRule).where(LabourCostRule.tenant_id == ctx.tenant_id, LabourCostRule.labour_type == n["employment_type"], LabourCostRule.role == n["role"],
                                                    LabourCostRule.position_grade == n.get("position_grade"), LabourCostRule.provider_id == n.get("provider_id"),
                                                    LabourCostRule.effective_from == datetime.fromisoformat(n["effective_from"]).replace(tzinfo=timezone.utc)))
        vals = dict(rate=f"{n['hourly_rate']:.2f}", overtime_multiplier=None if n["overtime_multiplier"] is None else f"{n['overtime_multiplier']:g}",
                    surcharge=None if n["surcharge"] is None else f"{n['surcharge']:.2f}", currency=n["currency"],
                    effective_to=datetime.fromisoformat(n["effective_to"]).replace(tzinfo=timezone.utc) if n.get("effective_to") else None)
        if c is None:
            db.add(LabourCostRule(tenant_id=ctx.tenant_id, labour_type=n["employment_type"], role=n["role"], position_grade=n.get("position_grade"), provider_id=n.get("provider_id"),
                                  effective_from=datetime.fromisoformat(n["effective_from"]).replace(tzinfo=timezone.utc), **vals))
            created += 1
        else:
            for k, v in vals.items():
                setattr(c, k, v)
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_productivity_loss(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.stage4 import ProductivityLoss
    created = updated = 0
    for r in good:
        n = r.normalised
        p = db.scalar(select(ProductivityLoss).where(ProductivityLoss.tenant_id == ctx.tenant_id, ProductivityLoss.site_id == n["site"], ProductivityLoss.loss_type == n["type"],
                                                      ProductivityLoss.activity == n.get("activity"), ProductivityLoss.weekday == n.get("weekday"), ProductivityLoss.shift_code == n.get("shift_code")))
        vals = dict(percent_loss=n["percent_loss"], off_task_hours=n["off_task_hours"])
        if p is None:
            db.add(ProductivityLoss(tenant_id=ctx.tenant_id, site_id=n["site"], loss_type=n["type"], activity=n.get("activity"), weekday=n.get("weekday"), shift_code=n.get("shift_code"), **vals))
            created += 1
        else:
            for k, v in vals.items():
                setattr(p, k, v)
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_staging_capacity(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.stage4 import StagingCapacity
    created = updated = 0
    for r in good:
        n = r.normalised
        c = db.scalar(select(StagingCapacity).where(StagingCapacity.tenant_id == ctx.tenant_id, StagingCapacity.site_id == n["site"], StagingCapacity.zone_id == n["zone_id"]))
        if c is None:
            db.add(StagingCapacity(tenant_id=ctx.tenant_id, site_id=n["site"], zone_id=n["zone_id"], capacity=n["capacity"], unit=n["unit"]))
            created += 1
        else:
            c.capacity, c.unit = n["capacity"], n["unit"]
            updated += 1
        r.applied = True
    return {"created": created, "updated": updated}


def _apply_staging_movements(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.stage4 import StagingMovement
    created = 0
    for r in good:
        n = r.normalised
        db.add(StagingMovement(tenant_id=ctx.tenant_id, site_id=n["site"], zone_id=n["zone_id"], occurred_at=datetime.fromisoformat(n["occurred_at"]),
                               movement_type=n["movement_type"], quantity=n["quantity"], unit=n["unit"]))
        created += 1
        r.applied = True
    return {"created": created}


def _apply_availability(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow]) -> dict:
    from app.models.canonical import Availability
    refs = {w.source_ref: w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.source_system == "tempo_import")) if w.source_ref}
    created = same = 0
    for r in good:
        n = r.normalised
        wid, st = refs[n["worker_ref"]], datetime.fromisoformat(n["start_at"])
        if db.scalar(select(Availability.id).where(Availability.tenant_id == ctx.tenant_id, Availability.worker_id == wid, Availability.status == n["kind"], Availability.interval_start == st).limit(1)):
            same += 1
            continue
        db.add(Availability(tenant_id=ctx.tenant_id, worker_id=wid, interval_start=st, interval_end=datetime.fromisoformat(n["end_at"]), status=n["kind"], source_system="tempo_import", source_ref=batch.id))
        created += 1
        r.applied = True
    return {"created": created, "unchanged": same}


def _apply_standards(db: Session, ctx: RequestContext, good: list[ImportRow]) -> dict:
    created = changed = same = 0
    for r in good:
        n = r.normalised
        start = datetime.fromisoformat(n["effective_from"]).replace(tzinfo=timezone.utc)
        cur = db.scalar(select(WorkStandard).where(WorkStandard.tenant_id == ctx.tenant_id, WorkStandard.activity == n["activity"], WorkStandard.effective_to.is_(None)))
        if cur is not None and abs(cur.time_per_unit_seconds - n["seconds_per_unit"]) < 1e-9:
            same += 1
            continue
        if cur is not None:
            if _aware(cur.effective_from) >= start:
                cur.time_per_unit_seconds = n["seconds_per_unit"]  # same-day correction, no new row
                changed += 1
                r.applied = True
                continue
            cur.effective_to = start
            changed += 1
        else:
            created += 1
        db.add(WorkStandard(tenant_id=ctx.tenant_id, activity=n["activity"], time_per_unit_seconds=n["seconds_per_unit"], effective_from=start))
        r.applied = True
    return {"created": created, "changed": changed, "unchanged": same}


def _apply_forecast(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow], opts: dict) -> dict:
    v = opts["forecast_version"]
    if db.scalar(select(SuppliedForecast.id).where(SuppliedForecast.tenant_id == ctx.tenant_id, SuppliedForecast.version == v, SuppliedForecast.state == "active").limit(1)):
        raise ImportProblem(f"the forecast label '{v}' was used by another upload in the meantime — give this revision a new label")
    gen = datetime.fromisoformat(opts["generated_at"]) if opts.get("generated_at") else None
    first: dict[str, datetime] = {}
    last: dict[str, datetime] = {}
    for r in good:
        n = r.normalised
        db.add(SuppliedForecast(tenant_id=ctx.tenant_id, site_id=n["site"], activity=n["activity"], bucket_start=datetime.fromisoformat(n["bucket_start"]), bucket_minutes=n["bucket_minutes"],
                                units=n["units"], lower=n.get("lower"), upper=n.get("upper"), version=v, batch_id=batch.id, generated_at=gen))
        t = datetime.fromisoformat(n["bucket_start"])
        first[n["site"]] = min(first.get(n["site"], t), t)
        last[n["site"]] = max(last.get(n["site"], t), t)
        r.applied = True
    flagged = _flag_rosters(db, ctx, first, last, v)
    return {"rows": len(good), "version": v, "rosters_flagged_for_review": flagged}


def _flag_rosters(db: Session, ctx: RequestContext, first: dict[str, datetime], last: dict[str, datetime], version: str) -> int:
    """A revised forecast tells open rosters (draft / awaiting approval / approved) to be reviewed. Published rosters are left alone."""
    n = 0
    tzs = _tz(db, ctx)
    for site, lo in first.items():
        hi = last[site]
        for v in db.scalars(select(RosterVersion).where(RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id == site, RosterVersion.state.in_(OPEN_ROSTER_STATES))):
            tz = tzs[site]
            ws = datetime.fromisoformat(v.week_start).replace(tzinfo=tz).astimezone(timezone.utc)
            we = ws + timedelta(days=v.days)
            if lo < we and hi + timedelta(days=1) > ws:
                db.add(RosterEvent(tenant_id=ctx.tenant_id, version_id=v.id, actor_user_id=ctx.user_id, action="forecast_revised", detail={"forecast_version": version}))
                nt.notify(db, ctx.tenant_id, nt.recipients(db, ctx.tenant_id, site, "labour.plan"), kind="forecast.revised", severity="action", title=f"Forecast revised — review the roster for week of {v.week_start}",
                          body=f"Forecast '{version}' changes the workload this roster was built on. It has not been changed.", link=f"/roster?start={v.week_start}&v={v.id}", site_id=site, dedup_key=f"forecast:{version}:{v.id}")
                n += 1
    return n


# --- authority and derived workload ---------------------------------------------------------------------------------------------
def _authority(db: Session, ctx: RequestContext, site: str, activity: str, kind: str, reason: str) -> str:
    p = db.get(ActualsPolicy, (ctx.tenant_id, site, activity))
    if p is None:
        db.add(ActualsPolicy(tenant_id=ctx.tenant_id, site_id=site, activity=activity, authority=kind, set_by=ctx.user_id, reason=reason))
        db.flush()
        return kind
    return p.authority


def _hour_floor(t: datetime, tz: ZoneInfo) -> datetime:
    return t.astimezone(tz).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def rebuild_hours(db: Session, ctx: RequestContext, slots: set[tuple[str, str, datetime]]) -> None:
    """Recompute hourly workload for each (site, activity, hour) from the active events. Rows owned by other sources are never touched."""
    for site, act, h in slots:
        db.execute(delete(DemandBucket).where(DemandBucket.tenant_id == ctx.tenant_id, DemandBucket.site_id == site, DemandBucket.activity == act,
                                              DemandBucket.interval_start == h, DemandBucket.bucket_minutes == 60, DemandBucket.source == TXN))
        tot: dict[str | None, float] = defaultdict(float)
        for e in db.scalars(select(WorkloadEvent).where(WorkloadEvent.tenant_id == ctx.tenant_id, WorkloadEvent.site_id == site, WorkloadEvent.activity == act,
                                                          WorkloadEvent.state == "active", WorkloadEvent.occurred_at >= h, WorkloadEvent.occurred_at < h + timedelta(hours=1))):
            tot[e.customer_id] += e.quantity
        for cust, q in tot.items():
            db.add(DemandBucket(tenant_id=ctx.tenant_id, activity=act, site_id=site, customer_id=cust, interval_start=h, volume=round(q, 6), source=TXN, bucket_minutes=60))


def _displace(db: Session, ctx: RequestContext, site: str, act: str, lo: datetime, hi: datetime, own: str, displaced: list[dict]) -> None:
    for b in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == ctx.tenant_id, DemandBucket.site_id == site, DemandBucket.activity == act,
                                                   DemandBucket.interval_start >= lo, DemandBucket.interval_start < hi, DemandBucket.source != own)):
        displaced.append({"site": site, "activity": act, "start": _aware(b.interval_start).isoformat(), "minutes": b.bucket_minutes, "volume": b.volume, "source": b.source, "customer": b.customer_id})
        db.delete(b)


def _apply_transactions(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow], opts: dict) -> dict:
    tzs = _tz(db, ctx)
    plan = _plan_events(db, ctx, good)  # recomputed against the database as it is now
    slots: set[tuple[str, str, datetime]] = set()
    counted: set[tuple[str, str]] = set()
    shadow: set[tuple[str, str]] = set()
    displaced: list[dict] = []
    stats = defaultdict(int)
    for r, p in zip(good, plan):
        n = r.normalised
        if any(m["level"] == "error" for m in p["messages"]):
            r.status, r.messages = "error", r.messages + p["messages"]
            stats["rejected"] += 1
            continue
        kind = p["plan"]
        stats[kind] += 1
        if kind in ("noop", "stale"):
            continue
        tz = tzs[n["site"]]
        occ = datetime.fromisoformat(n["occurred_at"])
        e = db.scalar(select(WorkloadEvent).where(WorkloadEvent.tenant_id == ctx.tenant_id, WorkloadEvent.source == n["source"], WorkloadEvent.event_id == n["event_id"]))
        prev = None
        if e is not None:
            prev = {"site": e.site_id, "activity": e.activity, "customer": e.customer_id, "occurred_at": _aware(e.occurred_at).isoformat(), "quantity": e.quantity, "unit": e.unit,
                    "revision": e.revision, "state": e.state, "payload_hash": e.payload_hash}
            slots.add((e.site_id, e.activity, _hour_floor(_aware(e.occurred_at), tzs[e.site_id])))
        rev = n.get("revision") or ((e.revision + 1) if e else 1)
        state = "cancelled" if n["action"] == "cancel" else "active"
        if e is None:
            e = WorkloadEvent(tenant_id=ctx.tenant_id, source=n["source"], event_id=n["event_id"], site_id=n["site"], activity=n["activity"], customer_id=n.get("customer"), occurred_at=occ,
                              quantity=n["quantity"], unit=n["unit"], revision=rev, state=state, payload_hash=n["_hash"], batch_id=batch.id)
            db.add(e)
        else:
            e.site_id, e.activity, e.customer_id, e.occurred_at, e.quantity, e.unit = n["site"], n["activity"], n.get("customer"), occ, n["quantity"], n["unit"]
            e.revision, e.state, e.payload_hash, e.batch_id, e.updated_at = rev, state, n["_hash"], batch.id, _now()
        db.flush()
        r.before = {"event_pk": e.id, "prev": prev}
        r.applied = True
        slots.add((n["site"], n["activity"], _hour_floor(occ, tz)))
    pairs = {(s, a) for s, a, _ in slots}
    for s, a in pairs:
        if _authority(db, ctx, s, a, "transactions", "first workload for this site and activity arrived as events") == "transactions":
            counted.add((s, a))
        else:
            shadow.add((s, a))
    live = {sl for sl in slots if (sl[0], sl[1]) in counted}
    if opts.get("take_over"):
        for s, a, h in live:
            _displace(db, ctx, s, a, h, h + timedelta(hours=1), TXN, displaced)
    rebuild_hours(db, ctx, live)
    return {"counts": dict(stats), "hours_recomputed": len(live), "not_counted_bulk_is_authoritative": sorted(f"{a}@{s}" for s, a in shadow), "displaced": displaced}


def _apply_bulk(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow], opts: dict) -> dict:
    tzs = _tz(db, ctx)
    displaced: list[dict] = []
    stats = defaultdict(int)
    pairs = {(r.normalised["site"], r.normalised["activity"]) for r in good}
    live_pairs = {(s, a) for s, a in pairs if _authority(db, ctx, s, a, "bulk", "first workload for this site and activity arrived as totals") == "bulk"}
    if opts["mode"] == "replace_slice":
        a, b = parse_local_date(opts["slice_start"]), parse_local_date(opts["slice_end"])
        for s, act in live_pairs:
            lo, hi = local_day_bounds(a, tzs[s])[0], local_day_bounds(b, tzs[s])[1]
            for row in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == ctx.tenant_id, DemandBucket.site_id == s, DemandBucket.activity == act, DemandBucket.source == BULK,
                                                             DemandBucket.interval_start >= lo, DemandBucket.interval_start < hi)):
                displaced.append({"site": s, "activity": act, "start": _aware(row.interval_start).isoformat(), "minutes": row.bucket_minutes, "volume": row.volume, "source": row.source, "customer": row.customer_id})
                db.delete(row)
    if opts.get("take_over"):
        for r in good:
            n = r.normalised
            if (n["site"], n["activity"]) in live_pairs:
                st = datetime.fromisoformat(n["bucket_start"])
                _displace(db, ctx, n["site"], n["activity"], st, st + timedelta(minutes=1), BULK, displaced)
    db.flush()
    for r in good:
        n = r.normalised
        if (n["site"], n["activity"]) not in live_pairs:
            stats["stored_not_counted"] += 1
            continue
        st = datetime.fromisoformat(n["bucket_start"])
        cust = n.get("customer")
        row = db.scalar(select(DemandBucket).where(DemandBucket.tenant_id == ctx.tenant_id, DemandBucket.site_id == n["site"], DemandBucket.activity == n["activity"], DemandBucket.interval_start == st,
                                                   DemandBucket.bucket_minutes == n["bucket_minutes"], DemandBucket.source == BULK,
                                                   DemandBucket.customer_id.is_(None) if cust is None else DemandBucket.customer_id == cust))
        if row is None:
            db.add(DemandBucket(tenant_id=ctx.tenant_id, activity=n["activity"], site_id=n["site"], customer_id=cust, interval_start=st, volume=n["units"], source=BULK, bucket_minutes=n["bucket_minutes"]))
            r.before = {"prev": None}
            stats["created"] += 1
        else:
            r.before = {"prev": row.volume}
            stats["updated" if abs(row.volume - n["units"]) > 1e-9 else "unchanged"] += 1
            row.volume = n["units"]
        r.applied = True
    return {"counts": dict(stats), "total_units_applied": round(sum(r.normalised["units"] for r in good if (r.normalised["site"], r.normalised["activity"]) in live_pairs), 3),
            "not_counted_events_are_authoritative": sorted(f"{a}@{s}" for s, a in pairs - live_pairs), "displaced": displaced}


# ------------------------------------------------------------------------------------------------------------------------- undo
def undo_batch(db: Session, ctx: RequestContext, batch: ImportBatch) -> ImportBatch:
    if batch.tenant_id != ctx.tenant_id:
        raise ImportProblem("batch not found")
    if batch.state == "undone":
        return batch
    if batch.state != "applied":
        raise ImportProblem(f"only an applied batch can be undone (this one is {batch.state})")
    if batch.data_class == "master" and batch.entity == "availability":
        from app.models.canonical import Availability
        for a in db.scalars(select(Availability).where(Availability.tenant_id == ctx.tenant_id, Availability.source_ref == batch.id, Availability.source_system == "tempo_import")):
            db.delete(a)
        batch.state, batch.undone_by, batch.undone_at = "undone", ctx.user_id, _now()
        auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="import.undo", decision="allowed", session_ref=batch.id, correlation_id=ctx.correlation_id)
        db.flush()
        return batch
    if batch.data_class == "master":
        raise ImportProblem("master-data imports other than availability cannot be undone automatically — correct them by uploading a fixed file")
    later = db.scalar(select(ImportBatch.id).where(ImportBatch.tenant_id == ctx.tenant_id, ImportBatch.data_class == batch.data_class, ImportBatch.state == "applied",
                                                   ImportBatch.applied_at > batch.applied_at).limit(1))
    if later:
        raise ImportProblem(f"a newer {batch.data_class} batch ({later}) has been applied since — undo that one first")
    rows = [r for r in _rows(db, batch) if r.applied]
    applied = (batch.summary or {}).get("applied", {})
    tzs = _tz(db, ctx)
    if batch.data_class == "forecast":
        for f in db.scalars(select(SuppliedForecast).where(SuppliedForecast.batch_id == batch.id)):
            f.state = "removed"
    elif batch.data_class == "transactions":
        slots: set[tuple[str, str, datetime]] = set()
        for r in rows:
            e = db.get(WorkloadEvent, r.before["event_pk"])
            slots.add((e.site_id, e.activity, _hour_floor(_aware(e.occurred_at), tzs[e.site_id])))
            prev = r.before.get("prev")
            if prev is None:
                e.state = "undone"
            else:
                e.site_id, e.activity, e.customer_id, e.occurred_at, e.quantity, e.unit = prev["site"], prev["activity"], prev["customer"], datetime.fromisoformat(prev["occurred_at"]), prev["quantity"], prev["unit"]
                e.revision, e.state, e.payload_hash = prev["revision"], prev["state"], prev["payload_hash"]
                slots.add((e.site_id, e.activity, _hour_floor(_aware(e.occurred_at), tzs[e.site_id])))
        db.flush()
        pol = {(p.site_id, p.activity): p.authority for p in db.scalars(select(ActualsPolicy).where(ActualsPolicy.tenant_id == ctx.tenant_id))}
        rebuild_hours(db, ctx, {sl for sl in slots if pol.get((sl[0], sl[1])) == "transactions"})
        db.flush()
        _restore(db, ctx, applied.get("displaced", []))
    else:
        for r in rows:
            n = r.normalised
            st = datetime.fromisoformat(n["bucket_start"])
            cust = n.get("customer")
            row = db.scalar(select(DemandBucket).where(DemandBucket.tenant_id == ctx.tenant_id, DemandBucket.site_id == n["site"], DemandBucket.activity == n["activity"], DemandBucket.interval_start == st,
                                                       DemandBucket.bucket_minutes == n["bucket_minutes"], DemandBucket.source == BULK, DemandBucket.customer_id.is_(None) if cust is None else DemandBucket.customer_id == cust))
            if row is None:
                continue
            if (r.before or {}).get("prev") is None:
                db.delete(row)
            else:
                row.volume = r.before["prev"]
        db.flush()   # deletions must be visible before displaced rows are put back
        _restore(db, ctx, applied.get("displaced", []))
    batch.state, batch.undone_by, batch.undone_at = "undone", ctx.user_id, _now()
    auth.audit(db, actor_type=("service" if ctx.user_id.startswith("svc:") else "user"), actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="import.undo", decision="allowed", session_ref=batch.id, correlation_id=ctx.correlation_id)
    db.flush()
    return batch


def _restore(db: Session, ctx: RequestContext, displaced: list[dict]) -> None:
    for d in displaced:
        st = datetime.fromisoformat(d["start"])
        if not db.scalar(select(DemandBucket.id).where(DemandBucket.tenant_id == ctx.tenant_id, DemandBucket.site_id == d["site"], DemandBucket.activity == d["activity"], DemandBucket.interval_start == st,
                                                       DemandBucket.bucket_minutes == d["minutes"], DemandBucket.source == d["source"]).limit(1)):
            db.add(DemandBucket(tenant_id=ctx.tenant_id, activity=d["activity"], site_id=d["site"], customer_id=d["customer"], interval_start=st, volume=d["volume"], source=d["source"], bucket_minutes=d["minutes"]))
