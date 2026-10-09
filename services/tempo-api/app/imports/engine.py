"""Stage → preview → apply → undo for every data class (roadmap M1). Both channels (CSV upload and API) call this; neither writes data itself.

Guarantees:
- nothing changes until a batch is *applied*; staging only records what was received and what would happen;
- the exact normalised rows that were previewed are the rows applied;
- the same content (or the same Idempotency-Key) never produces a second batch or double counts workload;
- raw evidence (batches, rows, events) is never deleted — undo changes state and rebuilds derived aggregates from the evidence;
- workload is counted from ONE authoritative kind (events or totals) per site + activity, and the choice is recorded and visible.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth
from app.imports import validate as V
from app.imports.contracts import CONTRACT_VERSION, MAX_ROWS, Contract, contract_for
from app.imports.parse import ImportProblem, local_day_bounds, parse_local_date, parse_moment
from app.models.canonical import AttendanceSession, DemandBucket, SkillCertification, Worker, WorkStandard
from app.models.directory import Customer, Site, WorkerPerson
from app.models.imports import ActualsPolicy, ImportBatch, ImportRow, SuppliedForecast, WorkloadEvent
from app.models.rosters import RosterEvent, RosterVersion
from app.schemas.tenancy import RequestContext

BULK, TXN = "import:bulk", "import:transactions"
SAMPLE_ERRORS = 50
SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------------------------------------------------- lookups
def lookups(db: Session, ctx: RequestContext) -> V.Lookups:
    from app.models.directory import Zone
    from app.models.scheduling import ShiftTemplate
    from app.solvers.shifts import shift_elapsed_minutes
    sites = {s.site_id: ZoneInfo(s.timezone) for s in db.scalars(select(Site).where(Site.tenant_id == ctx.tenant_id)) if s.site_id in ctx.site_ids}
    now = _now()
    acts = {w.activity for w in db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == ctx.tenant_id)) if w.effective_to is None or _aware(w.effective_to) > now}
    customers = {c.customer_id for c in db.scalars(select(Customer).where(Customer.tenant_id == ctx.tenant_id))}
    refs = {w.source_ref: w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.source_system == "tempo_import")) if w.source_ref}
    existing = {x.site_id: x.timezone for x in db.scalars(select(Site).where(Site.tenant_id == ctx.tenant_id))}
    wsite = {w.source_ref: w.home_site for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.source_system == "tempo_import")) if w.source_ref}
    zone_ids = {(z.site_id, z.zone_id) for z in db.scalars(select(Zone).where(Zone.tenant_id == ctx.tenant_id))}
    from app.models.scheduling import OperatingCalendarDay
    cal = {(c.site_id, c.weekday): {"is_24h": c.is_24h, "is_closed": c.is_closed, "open_time": c.open_time, "close_time": c.close_time}
           for c in db.scalars(select(OperatingCalendarDay).where(OperatingCalendarDay.tenant_id == ctx.tenant_id))}
    tmpl = {(t.site_id, t.shift_code): {"elapsed_minutes": shift_elapsed_minutes(t.start_time, t.end_time)}
            for t in db.scalars(select(ShiftTemplate).where(ShiftTemplate.tenant_id == ctx.tenant_id, ShiftTemplate.effective_to.is_(None)))}
    from app.models.orders import ProcessTemplate
    proc = {(p.site_id, p.process_code) for p in db.scalars(select(ProcessTemplate).where(ProcessTemplate.tenant_id == ctx.tenant_id))}
    from app.models.canonical import LabourProvider
    providers = {p.provider_id for p in db.scalars(select(LabourProvider).where(LabourProvider.tenant_id == ctx.tenant_id))}
    from app.models.stage4 import StagingCapacity
    staging_units = {(c.site_id, c.zone_id): c.unit for c in db.scalars(select(StagingCapacity).where(StagingCapacity.tenant_id == ctx.tenant_id))}
    from app.models.constraints import Equipment
    equipment_ids = {(e.site_id, e.equipment_id) for e in db.scalars(select(Equipment).where(Equipment.tenant_id == ctx.tenant_id))}
    return V.Lookups(sites=sites, activities=acts, customers=customers, workers_by_ref=refs, existing_sites=existing, worker_site=wsite,
                      zone_ids=zone_ids, operating_calendar=cal, shift_templates=tmpl, process_templates=proc,
                      labour_providers=providers, staging_units=staging_units, equipment_ids=equipment_ids)


# --------------------------------------------------------------------------------------------------------------------- options
def check_options(contract: Contract, options: dict) -> dict:
    o = dict(options or {})
    if contract.data_class == "forecast":
        v = str(o.get("forecast_version", "")).strip()
        if not v:
            raise ImportProblem("forecast_version is required — give this forecast a label such as 2026-10-W2-v1")
        if len(v) > 80:
            raise ImportProblem("forecast_version is too long (80 characters)")
        o = {"forecast_version": v}
        if str(options.get("generated_at", "")).strip():
            o["generated_at"] = parse_moment(str(options["generated_at"]), ZoneInfo("UTC")).isoformat()
    elif contract.data_class == "bulk":
        mode = str(o.get("mode", "upsert") or "upsert")
        if mode not in ("upsert", "replace_slice"):
            raise ImportProblem("mode must be upsert or replace_slice")
        res: dict = {"mode": mode, "take_over": str(o.get("take_over", "false")).lower() in ("1", "true", "yes")}
        if mode == "replace_slice":
            if not (str(o.get("slice_start", "")).strip() and str(o.get("slice_end", "")).strip()):
                raise ImportProblem("replace_slice needs slice_start and slice_end — an ambiguous replacement is refused")
            a, b = parse_local_date(str(o["slice_start"])), parse_local_date(str(o["slice_end"]))
            if b < a or (b - a).days > 92:
                raise ImportProblem("the slice must end on or after it starts and cover at most 93 days")
            res.update(slice_start=a.isoformat(), slice_end=b.isoformat())
        elif str(o.get("slice_start", "")).strip() or str(o.get("slice_end", "")).strip():
            raise ImportProblem("slice_start/slice_end only apply to replace_slice — choose that mode or remove the dates")
        if str(o.get("control_total", "")).strip() != "":
            res["control_total"] = V._num(str(o["control_total"]), "control_total")
        o = res
    elif contract.data_class == "transactions":
        o = {"take_over": str(o.get("take_over", "false")).lower() in ("1", "true", "yes")}
    else:
        o = {}
    return o


# --------------------------------------------------------------------------------------------------------------------- stage
def stage(db: Session, ctx: RequestContext, *, data_class: str, entity: str | None, channel: str, source_label: str, rows: list[dict],
          options: dict | None = None, idempotency_key: str | None = None, raw_sha: str | None = None) -> tuple[ImportBatch, bool]:
    """Returns (batch, replayed). `replayed` means an identical earlier batch/key was found and nothing new was created."""
    contract = contract_for(data_class, entity)
    entity = entity if data_class == "master" else None
    if not rows:
        raise ImportProblem("there are no data rows")
    if len(rows) > MAX_ROWS:
        raise ImportProblem(f"more than {MAX_ROWS:,} rows in one batch — split it")
    opts = check_options(contract, options or {})
    clean = [{f.name: ("" if r.get(f.name) is None else str(r.get(f.name))) for f in contract.fields} for r in rows]
    sha = raw_sha or V.canonical_hash({"c": data_class, "e": entity, "o": opts, "rows": clean})
    q = select(ImportBatch).where(ImportBatch.tenant_id == ctx.tenant_id)
    if idempotency_key:
        prev = db.scalar(q.where(ImportBatch.idempotency_key == idempotency_key))
        if prev is not None:
            if prev.content_sha256 != sha:
                raise ImportProblem("this Idempotency-Key was already used for different content")
            return prev, True
    same = db.scalar(q.where(ImportBatch.data_class == data_class, ImportBatch.entity == entity, ImportBatch.content_sha256 == sha,
                             ImportBatch.state.in_(("applied", "validated"))).order_by(ImportBatch.created_at.desc()).limit(1))
    if same is not None:
        return same, True

    lk = lookups(db, ctx)
    batch = ImportBatch(tenant_id=ctx.tenant_id, data_class=data_class, entity=entity, channel=channel, source_label=source_label[:200], content_sha256=sha,
                        contract_version=CONTRACT_VERSION, mode=opts.get("mode", "upsert"), idempotency_key=idempotency_key, total_rows=len(clean), created_by=ctx.user_id)
    db.add(batch)
    db.flush()
    seen: dict[tuple, int] = {}
    ok = warn = bad = 0
    store: list[ImportRow] = []
    for i, raw in enumerate(clean, start=1):
        n, msgs = V.validate_row(contract, raw, lk)
        if n is not None:
            k = V.row_key(data_class, entity, n)
            if k in seen:
                msgs.append(V._msg("error", "", "duplicate", f"duplicates row {seen[k]} in this file (same {', '.join(contract.key)})"))
                n = None
            else:
                seen[k] = i
        status = "error" if any(m["level"] == "error" for m in msgs) else ("warning" if msgs else "ok")
        ok += status == "ok"
        warn += status == "warning"
        bad += status == "error"
        store.append(ImportRow(tenant_id=ctx.tenant_id, batch_id=batch.id, row_no=i, status=status, messages=msgs, raw=raw, normalised=n if status != "error" else None))
    db.add_all(store)
    batch.ok_rows, batch.warning_rows, batch.error_rows = ok, warn, bad
    summary = _preview(db, ctx, batch, contract, store, opts, lk)
    batch.ok_rows = sum(1 for r in store if r.status == "ok")      # previews can reclassify rows (stale events, rows outside a slice)
    batch.warning_rows = sum(1 for r in store if r.status == "warning")
    batch.error_rows = sum(1 for r in store if r.status == "error")
    batch.summary = summary
    if summary.get("blocking"):
        batch.state = "validated"
    db.flush()
    auth.audit(db, actor_type=("service" if ctx.user_id.startswith("svc:") else "user"), actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="import.stage", decision="allowed", reason_code=f"{data_class}:{channel}:rows={len(clean)}:errors={bad}", session_ref=batch.id, correlation_id=ctx.correlation_id)
    return batch, False


def _good(store: list[ImportRow]) -> list[ImportRow]:
    return [r for r in store if r.status != "error" and r.normalised]


def _master_preview(db: Session, ctx: RequestContext, entity: str, good: list[ImportRow], lk: V.Lookups, s: dict) -> None:
    from app.models.canonical import ActivityRoleZoneMap, Availability, LabourCostRule
    from app.models.directory import Zone
    from app.models.scheduling import OperatingCalendarDay, ShiftTemplate
    if entity == "zones":
        have = {(z.site_id, z.zone_id) for z in db.scalars(select(Zone).where(Zone.tenant_id == ctx.tenant_id))}
        for r in good:
            s["updates" if (r.normalised["site"], r.normalised["zone_id"]) in have else "creates"] += 1
    elif entity == "activity_roles":
        have = {(m.site_id, m.activity, m.role, m.zone) for m in db.scalars(select(ActivityRoleZoneMap).where(ActivityRoleZoneMap.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n["site"], n["activity"], n["role"], n["zone_id"]) in have else "creates"] += 1
    elif entity == "operating_calendar":
        have = {(c.site_id, c.weekday) for c in db.scalars(select(OperatingCalendarDay).where(OperatingCalendarDay.tenant_id == ctx.tenant_id))}
        for r in good:
            s["updates" if (r.normalised["site"], r.normalised["weekday"]) in have else "creates"] += 1
    elif entity == "shift_templates":
        have = {(t.site_id, t.shift_code) for t in db.scalars(select(ShiftTemplate).where(ShiftTemplate.tenant_id == ctx.tenant_id, ShiftTemplate.effective_to.is_(None)))}
        for r in good:
            s["updates" if (r.normalised["site"], r.normalised["shift_code"]) in have else "creates"] += 1
    elif entity == "shift_breaks":
        s["creates"] = len(good)  # breaks are keyed by (shift, offset, duration); re-uploading an identical file is a no-op via content-hash dedup, not row-level matching
    elif entity == "process_templates":
        from app.models.orders import ProcessTemplate
        have = {(p.site_id, p.process_code, p.customer_id) for p in db.scalars(select(ProcessTemplate).where(ProcessTemplate.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n["site"], n["process_code"], n["customer_id"]) in have else "creates"] += 1
    elif entity == "process_steps":
        from app.models.orders import ProcessStep, ProcessTemplate
        tmpl_ids = {(t.site_id, t.process_code): t.id for t in db.scalars(select(ProcessTemplate).where(ProcessTemplate.tenant_id == ctx.tenant_id))}
        have = {(s2.process_template_id, s2.sequence) for s2 in db.scalars(select(ProcessStep).where(ProcessStep.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            tid = tmpl_ids.get((n["site"], n["process_code"]))
            s["updates" if (tid, n["sequence"]) in have else "creates"] += 1
    elif entity == "orders":
        from app.models.orders import Order
        have = {o.order_ref for o in db.scalars(select(Order).where(Order.tenant_id == ctx.tenant_id))}
        for r in good:
            s["updates" if r.normalised["order_id"] in have else "creates"] += 1
    elif entity == "worker_activity_rates":
        s["creates"] = len(good)  # keyed by (worker, activity, effective_from); a same-day correction is detected at apply time
    elif entity == "unit_conversions":
        from app.models.orders import UnitConversion
        have = {(c.activity, c.from_unit, c.to_unit) for c in db.scalars(select(UnitConversion).where(UnitConversion.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n.get("activity"), n["from_unit"], n["to_unit"]) in have else "creates"] += 1
    elif entity == "fill_priorities":
        from app.models.constraints import FillPriority
        have = {(p.scope, p.value) for p in db.scalars(select(FillPriority).where(FillPriority.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n["scope"], n["value"]) in have else "creates"] += 1
    elif entity == "absenteeism":
        from app.models.constraints import AbsenteeismRule
        have = {(a.site_id, a.activity, a.weekday, a.shift_code) for a in db.scalars(select(AbsenteeismRule).where(AbsenteeismRule.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n["site"], n.get("activity"), n.get("weekday"), n.get("shift_code")) in have else "creates"] += 1
    elif entity == "equipment":
        from app.models.constraints import Equipment
        have = {(e.site_id, e.equipment_id) for e in db.scalars(select(Equipment).where(Equipment.tenant_id == ctx.tenant_id))}
        for r in good:
            s["updates" if (r.normalised["site"], r.normalised["equipment_id"]) in have else "creates"] += 1
    elif entity == "headcount_limits":
        from app.models.constraints import HeadcountLimit
        have = {(h.site_id, h.activity, h.shift_code) for h in db.scalars(select(HeadcountLimit).where(HeadcountLimit.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n["site"], n["activity"], n.get("shift_code")) in have else "creates"] += 1
    elif entity == "grade_rates":
        from app.models.canonical import LabourCostRule
        have = {(c.labour_type, c.role, c.position_grade, c.provider_id) for c in db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == ctx.tenant_id, LabourCostRule.position_grade.isnot(None) | LabourCostRule.provider_id.isnot(None)))}
        for r in good:
            n = r.normalised
            s["updates" if (n["employment_type"], n["role"], n.get("position_grade"), n.get("provider_id")) in have else "creates"] += 1
    elif entity == "productivity_loss":
        from app.models.stage4 import ProductivityLoss
        have = {(p.site_id, p.loss_type, p.activity, p.weekday, p.shift_code) for p in db.scalars(select(ProductivityLoss).where(ProductivityLoss.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n["site"], n["type"], n.get("activity"), n.get("weekday"), n.get("shift_code")) in have else "creates"] += 1
    elif entity == "staging_capacity":
        from app.models.stage4 import StagingCapacity
        have = {(c.site_id, c.zone_id) for c in db.scalars(select(StagingCapacity).where(StagingCapacity.tenant_id == ctx.tenant_id))}
        for r in good:
            s["updates" if (r.normalised["site"], r.normalised["zone_id"]) in have else "creates"] += 1
    elif entity == "staging_movements":
        s["creates"] = len(good)  # append-only event log; keyed by (site, zone, occurred_at, movement_type)
    elif entity == "indirect_headcount":
        from app.models.indirect import IndirectHeadcountRequirement
        have = {(h.site_id, h.role, h.weekday, h.start_time, h.end_time) for h in db.scalars(select(IndirectHeadcountRequirement).where(IndirectHeadcountRequirement.tenant_id == ctx.tenant_id))}
        for r in good:
            n = r.normalised
            s["updates" if (n["site"], n["role"], n["weekday"], n["start_time"], n["end_time"]) in have else "creates"] += 1
    elif entity == "sites":
        if not ctx.has_permission("labour.configure"):
            s["blocking"].append("Adding or changing sites needs the configure permission (a tenant administrator).")
        have = lk.existing_sites
        for r in good:
            s["updates" if r.normalised["site_id"] in have else "creates"] += 1
        s["notes"].append("You will be given access to any new site. Give others access in Administration.")
    elif entity == "customers":
        have = set(lk.customers)
        for r in good:
            s["updates" if r.normalised["customer_id"] in have else "creates"] += 1
    elif entity == "rates":
        cur = {(x.labour_type, x.role): x for x in db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == ctx.tenant_id))}
        for r in good:
            c = cur.get((r.normalised["employment_type"], r.normalised["role"]))
            s["creates" if c is None else ("unchanged" if abs(float(c.rate) - r.normalised["hourly_rate"]) < 1e-9 else "updates")] += 1
    else:
        wid = lk.workers_by_ref
        have = {(a.worker_id, a.status, _aware(a.interval_start)) for a in db.scalars(select(Availability).where(Availability.tenant_id == ctx.tenant_id, Availability.worker_id.in_(list(wid.values()) or [""])))}
        for r in good:
            n = r.normalised
            key = (wid[n["worker_ref"]], n["kind"], datetime.fromisoformat(n["start_at"]))
            s["unchanged" if key in have else "creates"] += 1


def _preview(db: Session, ctx: RequestContext, batch: ImportBatch, contract: Contract, store: list[ImportRow], opts: dict, lk: V.Lookups) -> dict:
    """What applying would do, plus anything that stops it. Pure reads."""
    s: dict = {"options": opts, "blocking": [], "notes": [], "creates": 0, "updates": 0, "unchanged": 0}
    good = _good(store)
    dc = batch.data_class
    if dc == "master" and batch.entity == "workers":
        for r in good:
            s["updates" if r.normalised["worker_ref"] in lk.workers_by_ref else "creates"] += 1
        s["unknown_skill_note"] = "Skills are added to the person; none are removed."
    elif dc == "master" and batch.entity in ("sites", "customers", "availability", "rates", "zones", "activity_roles", "operating_calendar", "shift_templates", "shift_breaks",
                                              "process_templates", "process_steps", "orders", "worker_activity_rates", "unit_conversions",
                                              "fill_priorities", "absenteeism", "equipment", "headcount_limits",
                                              "grade_rates", "productivity_loss", "staging_capacity", "staging_movements", "indirect_headcount"):
        _master_preview(db, ctx, batch.entity, good, lk, s)
    elif dc == "master":
        cur = {w.activity: w for w in db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == ctx.tenant_id, WorkStandard.effective_to.is_(None)))}
        for r in good:
            c = cur.get(r.normalised["activity"])
            if c is None:
                s["creates"] += 1
            elif abs(c.time_per_unit_seconds - r.normalised["seconds_per_unit"]) < 1e-9:
                s["unchanged"] += 1
            else:
                s["updates"] += 1
    elif dc == "forecast":
        v = opts["forecast_version"]
        used = db.scalar(select(SuppliedForecast.batch_id).where(SuppliedForecast.tenant_id == ctx.tenant_id, SuppliedForecast.version == v, SuppliedForecast.state == "active").limit(1))
        if used:
            s["blocking"].append(f"the forecast label '{v}' was already used (batch {used}). Give this revision a new label.")
        s["creates"] = len(good)
        s["total_units"] = round(sum(r.normalised["units"] for r in good), 3)
        s["sites"] = sorted({r.normalised["site"] for r in good})
    elif dc == "transactions":
        plan = _plan_events(db, ctx, good)
        for r, p in zip(good, plan):
            r.messages = [m for m in r.messages if m.get("code") not in ("replay", "stale", "conflict", "info")] + p["messages"]
            if any(m["level"] == "error" for m in r.messages):
                r.status, r.normalised = "error", None
            else:
                r.status = "warning" if r.messages else "ok"
                r.normalised = {**r.normalised, "_plan": p["plan"]}   # reassigned so the change is persisted
        batch.ok_rows = sum(1 for r in store if r.status == "ok")
        batch.warning_rows = sum(1 for r in store if r.status == "warning")
        batch.error_rows = sum(1 for r in store if r.status == "error")
        good = _good(store)
        counts = defaultdict(int)
        for r in good:
            counts[r.normalised["_plan"]] += 1
        s["creates"], s["updates"], s["unchanged"] = counts["insert"], counts["correct"] + counts["cancel"], counts["noop"] + counts["stale"]
        s["total_units"] = round(sum(r.normalised["quantity"] for r in good if r.normalised["_plan"] in ("insert", "correct") and r.normalised["action"] != "cancel"), 3)
        _authority_notes(db, ctx, good, "transactions", s)
        _takeover_check(db, ctx, good, opts, s, TXN, hourly=True)
    elif dc == "bulk":
        _plan_bulk(db, ctx, batch, good, opts, lk, s)
    return s


def _plan_events(db: Session, ctx: RequestContext, good: list[ImportRow]) -> list[dict]:
    ids = {(r.normalised["source"], r.normalised["event_id"]) for r in good}
    have: dict[tuple, WorkloadEvent] = {}
    if ids:
        for e in db.scalars(select(WorkloadEvent).where(WorkloadEvent.tenant_id == ctx.tenant_id, WorkloadEvent.event_id.in_({i[1] for i in ids}))):
            have[(e.source, e.event_id)] = e
    out = []
    shadow: dict[tuple, int] = {}
    units: dict[tuple[str, str], str] = {}
    for e in db.scalars(select(WorkloadEvent).where(WorkloadEvent.tenant_id == ctx.tenant_id, WorkloadEvent.state == "active").order_by(WorkloadEvent.updated_at.desc()).limit(5000)):
        units.setdefault((e.site_id, e.activity), e.unit)
    for r in good:
        n = r.normalised
        n.pop("_plan", None)
        e = have.get((n["source"], n["event_id"]))
        h = V.canonical_hash({k: n[k] for k in ("site", "activity", "occurred_at", "quantity", "unit", "customer", "action")})
        msgs: list[dict] = []
        plan = "insert"
        rev = n.get("revision")
        cur_rev = shadow.get((n["source"], n["event_id"]), e.revision if e else 0)
        if e is None and n["action"] == "correct":
            msgs.append(V._msg("error", "action", "conflict", "this event has not been received yet — send it with action=create first"))
        elif e is None:
            plan = "insert"
        elif e.state == "cancelled" and n["action"] == "create" and (rev or 1) <= e.revision:
            plan = "stale"; msgs.append(V._msg("warning", "revision", "stale", "ignored: a later cancellation for this event was already received"))
        elif e.payload_hash == h and (rev is None or rev == e.revision):
            plan = "noop"; msgs.append(V._msg("warning", "event_id", "replay", "already received — no change"))
        elif rev is not None and rev <= e.revision:
            plan = "stale"; msgs.append(V._msg("warning", "revision", "stale", f"ignored: revision {rev} is not newer than the revision held ({e.revision})"))
        elif rev is None and n["action"] == "create":
            msgs.append(V._msg("error", "event_id", "conflict", "this event already exists with different data — resend it with action=correct and a higher revision"))
        else:
            plan = "cancel" if n["action"] == "cancel" else "correct"
        first = units.setdefault((n["site"], n["activity"]), n["unit"])
        if first != n["unit"] and plan in ("insert", "correct"):
            plan = "insert"
            msgs.append(V._msg("error", "unit", "unit_mismatch", f"unit '{n['unit']}' differs from '{first}' already used for {n['activity']} at {n['site']} — one unit per activity, or convert before sending"))
        n["_hash"] = h
        shadow[(n["source"], n["event_id"])] = max(cur_rev, rev or 0)
        out.append({"plan": plan, "messages": msgs})
    return out


def _authority_notes(db: Session, ctx: RequestContext, good: list[ImportRow], kind: str, s: dict) -> None:
    pairs = {(r.normalised["site"], r.normalised["activity"]) for r in good}
    pol = {(p.site_id, p.activity): p.authority for p in db.scalars(select(ActualsPolicy).where(ActualsPolicy.tenant_id == ctx.tenant_id))}
    shadow = sorted(f"{a} at {si}" for si, a in pairs if pol.get((si, a)) not in (None, kind))
    s["shadowed"] = shadow
    if shadow:
        s["notes"].append(f"Stored but NOT counted as workload ({'bulk totals' if kind == 'transactions' else 'events'} are authoritative for: {', '.join(shadow[:10])}). "
                          "Change the authority for a site and activity to switch.")
    s["will_become_authoritative"] = sorted(f"{a} at {si}" for si, a in pairs if (si, a) not in pol)


def _takeover_check(db: Session, ctx: RequestContext, good: list[ImportRow], opts: dict, s: dict, own_source: str, *, hourly: bool) -> None:
    """Workload already present from a *different* source for the same periods must be replaced deliberately, never silently."""
    foreign: dict[str, int] = defaultdict(int)
    by: dict[tuple, list[datetime]] = defaultdict(list)
    kind = "transactions" if own_source == TXN else "bulk"
    pol = {(p.site_id, p.activity): p.authority for p in db.scalars(select(ActualsPolicy).where(ActualsPolicy.tenant_id == ctx.tenant_id))}
    for r in good:
        n = r.normalised
        if pol.get((n["site"], n["activity"]), kind) != kind:
            continue   # stored but not counted: it cannot collide with workload that is counted
        if own_source == TXN and n["action"] == "cancel":
            continue
        t = datetime.fromisoformat(n["occurred_at"] if "occurred_at" in n else n["bucket_start"])
        by[(n["site"], n["activity"])].append(t)
    for (site, act), ts in by.items():
        lo, hi = min(ts) - timedelta(hours=1), max(ts) + timedelta(days=1)
        for src in db.scalars(select(DemandBucket.source).where(DemandBucket.tenant_id == ctx.tenant_id, DemandBucket.site_id == site, DemandBucket.activity == act,
                                                                 DemandBucket.interval_start >= lo, DemandBucket.interval_start <= hi, DemandBucket.source != own_source)):
            foreign[src] += 1
    s["foreign_sources"] = dict(foreign)
    if foreign:
        if opts.get("take_over"):
            s["notes"].append("Workload from other sources for these periods will be replaced (take-over was requested): " + ", ".join(f"{k} ({v} periods)" for k, v in foreign.items()))
        else:
            s["blocking"].append("workload for some of these periods already came from another source (" + ", ".join(f"{k}: {v} periods" for k, v in foreign.items())
                                 + "). Tick 'take over' to replace it deliberately, or change the dates.")


def _plan_bulk(db: Session, ctx: RequestContext, batch: ImportBatch, good: list[ImportRow], opts: dict, lk: V.Lookups, s: dict) -> None:
    s["total_units"] = round(sum(r.normalised["units"] for r in good), 3)
    ct = opts.get("control_total")
    if ct is not None:
        s["control_total"], s["control_difference"] = ct, round(s["total_units"] - ct, 3)
        if abs(s["total_units"] - ct) > 1e-6 * max(1.0, abs(ct)):
            s["blocking"].append(f"the file adds up to {s['total_units']:,.3f} units but you stated {ct:,.3f}. Fix the file or the control total.")
    if opts["mode"] == "replace_slice":
        a, b = parse_local_date(opts["slice_start"]), parse_local_date(opts["slice_end"])
        missing: list[str] = []
        for r in list(good):
            n = r.normalised
            tz = lk.sites[n["site"]]
            ld = datetime.fromisoformat(n["bucket_start"]).astimezone(tz).date()
            if not (a <= ld <= b):
                r.status, r.normalised = "error", None
                r.messages = r.messages + [V._msg("error", "period_start", "outside_slice", f"{ld} is outside the stated slice {a} to {b}")]
        good2 = _good([r for r in good])
        have: dict[tuple, set] = defaultdict(set)
        for r in good2:
            n = r.normalised
            have[(n["site"], n["activity"], n["bucket_minutes"])].add(datetime.fromisoformat(n["bucket_start"]).astimezone(lk.sites[n["site"]]).date())
        for (site, act, minutes), days in have.items():
            if minutes == 1440:
                for d in (a + timedelta(days=i) for i in range((b - a).days + 1)):
                    if d not in days:
                        missing.append(f"{act} at {site}: {d}")
        s["incomplete_periods"] = len(missing)
        s["incomplete_sample"] = missing[:20]
        if missing:
            s["notes"].append(f"{len(missing)} day(s) in the slice have no value and will become empty (they are replaced, not kept).")
        good = good2
    _authority_notes(db, ctx, good, "bulk", s)
    s["creates"] = len(good)
    _takeover_check(db, ctx, good, opts, s, BULK, hourly=False)
