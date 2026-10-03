"""Customer data ingestion: CSV upload and API submission share one engine (app/imports). Contracts, templates and error files are
generated from the same definitions the validators use."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session


from app.core import auth, service_auth
from app.dependencies import get_db, get_principal, get_request_context
from app.errors import AuthForbidden, AuthInvalid, PolicyConflict, RunNotFound, ScopeError
from app.imports import apply as A, engine as E, parse as P
from app.imports.contracts import CONTRACTS, CONTRACT_VERSION, DATA_CLASSES, MAX_ROWS, contract_for, describe, template_csv
from app.models.directory import Site
from app.models.imports import ActualsPolicy, ImportBatch, ImportMapping, ImportRow, SiteForecastPreference, SuppliedForecast
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["imports"])
PERM = "labour.data.import"


def import_context(request: Request, db: Session = Depends(get_db)) -> RequestContext:
    """A signed-in person (cookie or bearer token) or a service credential (`Authorization: Bearer tsc_…`)."""
    h = request.headers.get("authorization", "")
    cid = getattr(request.state, "correlation_id", "cor_unknown")
    if h.lower().startswith("bearer tsc_"):
        ctx = service_auth.resolve(db, h[7:].strip(), cid)
    else:
        principal = get_principal(request, db, request.headers.get("x-tempo-tenant"))
        ctx = get_request_context(request, principal, db)
    if not ctx.has_permission(PERM):
        raise AuthForbidden(f"caller lacks {PERM}")
    return ctx


def _problem(e: P.ImportProblem) -> ScopeError:
    return ScopeError(str(e))


def _contract(data_class: str, entity: str | None):
    try:
        return contract_for(data_class, entity)
    except KeyError as e:
        raise RunNotFound(str(e).strip("'\"")) from None


def view(b: ImportBatch, *, replayed: bool = False, errors: list[ImportRow] | None = None) -> dict:
    out = {"id": b.id, "data_class": b.data_class, "entity": b.entity, "channel": b.channel, "source_label": b.source_label, "state": b.state, "mode": b.mode, "contract_version": b.contract_version,
           "total_rows": b.total_rows, "ok_rows": b.ok_rows, "warning_rows": b.warning_rows, "error_rows": b.error_rows, "summary": b.summary or {}, "created_by": b.created_by,
           "created_at": b.created_at, "applied_at": b.applied_at, "applied_by": b.applied_by, "undone_at": b.undone_at, "replayed": replayed,
           "can_apply": b.state == "validated" and not (b.summary or {}).get("blocking") and (b.ok_rows + b.warning_rows) > 0,
           "can_undo": b.state == "applied" and b.data_class != "master"}
    if errors is not None:
        out["rejected_sample"] = [{"row": r.row_no, "messages": r.messages, "values": r.raw} for r in errors]
    return out


def _sample_errors(db: Session, b: ImportBatch, limit: int = E.SAMPLE_ERRORS) -> list[ImportRow]:
    return list(db.scalars(select(ImportRow).where(ImportRow.batch_id == b.id, ImportRow.status == "error").order_by(ImportRow.row_no).limit(limit)))


# ------------------------------------------------------------------------------------------------------------------ contracts
@router.get("/imports/contracts")
def contracts(ctx: RequestContext = Depends(import_context)) -> dict:
    return {"contract_version": CONTRACT_VERSION, "contracts": [describe(c) for c in CONTRACTS.values()]}


@router.get("/imports/contracts/{data_class}")
def one_contract(data_class: str, entity: str | None = None, ctx: RequestContext = Depends(import_context)) -> dict:
    return describe(_contract(data_class, entity))


@router.get("/imports/contracts/{data_class}/template.csv")
def template(data_class: str, entity: str | None = None, ctx: RequestContext = Depends(import_context)) -> Response:
    c = _contract(data_class, entity)
    name = f"tempo-template-{data_class}{'-' + entity if entity else ''}.csv"
    return Response(template_csv(c), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------------------------------------------------------ CSV channel
def _saved(db: Session, ctx: RequestContext, data_class: str, entity: str | None) -> dict | None:
    m = db.scalar(select(ImportMapping).where(ImportMapping.tenant_id == ctx.tenant_id, ImportMapping.data_class == data_class, ImportMapping.entity == (entity or ""), ImportMapping.name == "default"))
    return m.mapping if m else None


@router.post("/imports/csv/inspect")
async def inspect_csv(request: Request, data_class: str, entity: str | None = None, ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> dict:
    """Reads the header and a few rows, and proposes a column mapping (the saved one first). Changes nothing."""
    c = _contract(data_class, entity)
    try:
        headers, rows = P.read_csv(await request.body())
    except P.ImportProblem as e:
        raise _problem(e) from None
    saved = _saved(db, ctx, data_class, entity)
    mapping = P.suggest_mapping(c, headers, saved)
    return {"headers": headers, "row_count": len(rows), "sample": rows[:5], "suggested_mapping": mapping, "used_saved_mapping": bool(saved),
            "missing_required": [f.name for f in c.fields if f.required and not mapping.get(f.name)], "fields": describe(c)["fields"], "batch_options": describe(c)["batch_options"]}


@router.post("/imports/csv/stage", status_code=201)
async def stage_csv(request: Request, data_class: str, entity: str | None = None, mapping: str = Query(default="{}"), save_mapping: bool = False,
                    file_name: str = "upload.csv", ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> dict:
    """Maps, validates and previews the file. Nothing is applied until /apply is called on the returned batch."""
    c = _contract(data_class, entity)
    body = await request.body()
    try:
        m = json.loads(mapping)
        headers, raw_rows = P.read_csv(body)
        if not isinstance(m, dict) or any(v is not None and v not in headers for v in m.values()):
            raise P.ImportProblem("the column mapping refers to a column that is not in the file")
        missing = [f.name for f in c.fields if f.required and not m.get(f.name)]
        if missing:
            raise P.ImportProblem("map a column for: " + ", ".join(missing))
        rows = P.apply_mapping(c, m, raw_rows)
        options = {k: v for k, v in request.query_params.items() if k in {f.name for f in c.batch_options}}
        sha = hashlib.sha256(body + json.dumps(m, sort_keys=True).encode() + json.dumps(options, sort_keys=True).encode()).hexdigest()
        batch, replayed = E.stage(db, ctx, data_class=data_class, entity=entity, channel="csv", source_label=file_name, rows=rows, options=options, raw_sha=sha)
    except json.JSONDecodeError:
        raise ScopeError("mapping must be JSON") from None
    except P.ImportProblem as e:
        raise _problem(e) from None
    if save_mapping and not replayed:
        row = db.scalar(select(ImportMapping).where(ImportMapping.tenant_id == ctx.tenant_id, ImportMapping.data_class == data_class, ImportMapping.entity == (entity or ""), ImportMapping.name == "default"))
        if row is None:
            db.add(ImportMapping(tenant_id=ctx.tenant_id, data_class=data_class, entity=entity or "", name="default", mapping=m, updated_by=ctx.user_id))
        else:
            row.mapping, row.updated_by, row.updated_at = m, ctx.user_id, datetime.now(timezone.utc)
    return view(batch, replayed=replayed, errors=_sample_errors(db, batch))


# ------------------------------------------------------------------------------------------------------------------ API channel
class BatchIn(BaseModel):
    data_class: str
    entity: str | None = None
    rows: list[dict] = Field(min_length=1)
    options: dict = Field(default_factory=dict)
    apply: bool = False   # one-call convenience for integrations: stage, and apply if nothing was rejected or held


@router.post("/imports/batches", status_code=201)
def submit_batch(body: BatchIn, ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)) -> dict:
    """API channel. Send an Idempotency-Key so a retry returns the same receipt instead of creating a second batch."""
    if len(body.rows) > MAX_ROWS:
        raise ScopeError(f"at most {MAX_ROWS:,} rows per request — split the batch")
    _contract(body.data_class, body.entity)
    try:
        batch, replayed = E.stage(db, ctx, data_class=body.data_class, entity=body.entity, channel="api", source_label=ctx.user_id, rows=body.rows, options=body.options, idempotency_key=idempotency_key)
        if body.apply and batch.state == "validated" and not replayed:
            if batch.error_rows == 0 and not (batch.summary or {}).get("blocking"):
                A.apply_batch(db, ctx, batch)
    except P.ImportProblem as e:
        raise _problem(e) from None
    return view(batch, replayed=replayed, errors=_sample_errors(db, batch))


# ------------------------------------------------------------------------------------------------------------------ batches
def _batch(db: Session, ctx: RequestContext, batch_id: str) -> ImportBatch:
    b = db.get(ImportBatch, batch_id)
    if b is None or b.tenant_id != ctx.tenant_id:
        raise RunNotFound("batch not found")
    return b


@router.get("/imports/batches")
def list_batches(data_class: str | None = None, limit: int = Query(default=30, ge=1, le=100), ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> list[dict]:
    q = select(ImportBatch).where(ImportBatch.tenant_id == ctx.tenant_id)
    if data_class:
        q = q.where(ImportBatch.data_class == data_class)
    return [view(b) for b in db.scalars(q.order_by(ImportBatch.created_at.desc()).limit(limit))]


@router.get("/imports/batches/{batch_id}")
def get_batch(batch_id: str, ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> dict:
    b = _batch(db, ctx, batch_id)
    return view(b, errors=_sample_errors(db, b))


@router.get("/imports/batches/{batch_id}/errors.csv")
def errors_csv(batch_id: str, ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> Response:
    """Every rejected row with the reasons, in the same columns as the upload, ready to fix and re-upload."""
    b = _batch(db, ctx, batch_id)
    rows = list(db.scalars(select(ImportRow).where(ImportRow.batch_id == b.id, ImportRow.status == "error").order_by(ImportRow.row_no)))
    cols = contract_for(b.data_class, b.entity).names
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["row", "problems"] + cols)
    for r in rows:
        from app.core.exports import safe_cell
        w.writerow([r.row_no, safe_cell(" | ".join(f"{m['field'] or 'row'}: {m['text']}" for m in r.messages if m["level"] == "error"))] + [safe_cell(r.raw.get(c, "")) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="tempo-rejected-rows-{b.id[-6:]}.csv"', "Cache-Control": "no-store"})


class ApplyIn(BaseModel):
    accept_partial: bool = False


@router.post("/imports/batches/{batch_id}/apply")
def apply_batch(batch_id: str, body: ApplyIn = Body(default_factory=ApplyIn), ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> dict:
    b = _batch(db, ctx, batch_id)
    try:
        A.apply_batch(db, ctx, b, accept_partial=body.accept_partial)
    except P.ImportProblem as e:
        raise PolicyConflict(str(e)) from None
    return view(b, errors=_sample_errors(db, b))


@router.post("/imports/batches/{batch_id}/undo")
def undo_batch(batch_id: str, ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> dict:
    b = _batch(db, ctx, batch_id)
    try:
        A.undo_batch(db, ctx, b)
    except P.ImportProblem as e:
        raise PolicyConflict(str(e)) from None
    return view(b)


# ------------------------------------------------------------------------------------------------------------------ data page
@router.get("/imports/status")
def status(ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> dict:
    """One simple view: per data class — last success, rows rejected, what is waiting — plus workload authority and forecast sources."""
    out = []
    for dc, entities in DATA_CLASSES.items():
        for ent in entities:
            q = select(ImportBatch).where(ImportBatch.tenant_id == ctx.tenant_id, ImportBatch.data_class == dc, ImportBatch.entity == ent)
            last = db.scalar(q.where(ImportBatch.state == "applied").order_by(ImportBatch.applied_at.desc()).limit(1))
            waiting = db.scalar(select(func.count()).select_from(ImportBatch).where(ImportBatch.tenant_id == ctx.tenant_id, ImportBatch.data_class == dc, ImportBatch.entity == ent, ImportBatch.state == "validated")) or 0
            rejected = db.scalar(select(func.coalesce(func.sum(ImportBatch.error_rows), 0)).where(ImportBatch.tenant_id == ctx.tenant_id, ImportBatch.data_class == dc, ImportBatch.entity == ent,
                                                                                            ImportBatch.state.in_(("applied", "validated")))) or 0
            out.append({"data_class": dc, "entity": ent, "title": contract_for(dc, ent).title, "last_success_at": last.applied_at if last else None, "last_batch": last.id if last else None,
                        "last_rows": (last.ok_rows + last.warning_rows) if last else None, "waiting_batches": waiting, "rejected_rows": int(rejected)})
    sites = {s.site_id: s.name for s in db.scalars(select(Site).where(Site.tenant_id == ctx.tenant_id)) if s.site_id in ctx.site_ids}
    pol = [{"site_id": p.site_id, "activity": p.activity, "authority": p.authority, "reason": p.reason, "set_at": p.set_at} for p in db.scalars(select(ActualsPolicy).where(ActualsPolicy.tenant_id == ctx.tenant_id)) if p.site_id in sites]
    prefs = {p.site_id: p.source for p in db.scalars(select(SiteForecastPreference).where(SiteForecastPreference.tenant_id == ctx.tenant_id))}
    versions = [{"site_id": site, "version": v, "rows": n, "first": f, "last": l, "created_at": c} for site, v, n, f, l, c in db.execute(
        select(SuppliedForecast.site_id, SuppliedForecast.version, func.count(), func.min(SuppliedForecast.bucket_start), func.max(SuppliedForecast.bucket_start), func.max(SuppliedForecast.created_at))
        .where(SuppliedForecast.tenant_id == ctx.tenant_id, SuppliedForecast.state == "active").group_by(SuppliedForecast.site_id, SuppliedForecast.version).order_by(func.max(SuppliedForecast.created_at).desc()).limit(30)) if site in sites]
    return {"classes": out, "sites": [{"site_id": k, "name": v, "forecast_source": prefs.get(k, "generated")} for k, v in sites.items()], "authority": pol, "forecast_versions": versions}


class PrefIn(BaseModel):
    source: str = Field(pattern="^(generated|supplied)$")


@router.put("/sites/{site_id}/forecast-source")
def set_forecast_source(site_id: str, body: PrefIn, ctx: RequestContext = Depends(import_context), db: Session = Depends(get_db)) -> dict:
    """Choose which forecast drives planning for a site. The change is audited and takes effect on the next forecast run."""
    if site_id not in ctx.site_ids:
        raise RunNotFound("site not found or not visible in caller scope")
    p = db.get(SiteForecastPreference, (ctx.tenant_id, site_id))
    if p is None:
        db.add(SiteForecastPreference(tenant_id=ctx.tenant_id, site_id=site_id, source=body.source, set_by=ctx.user_id))
    else:
        p.source, p.set_by, p.set_at = body.source, ctx.user_id, datetime.now(timezone.utc)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="forecast.source", decision="allowed", reason_code=body.source, session_ref=site_id, correlation_id=ctx.correlation_id)
    return {"site_id": site_id, "forecast_source": body.source}


# ------------------------------------------------------------------------------------------------------------------ guided setup
@router.get("/setup/checklist")
def checklist(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Plain-language progress for a new customer: what is done, what is missing, and where to go next. Counts only what the caller can see."""
    from app.models.canonical import DemandBucket, Worker, WorkStandard
    from app.models.identity import Tenant
    from app.models.rosters import RosterVersion
    t = db.get(Tenant, ctx.tenant_id)
    sites = list(db.scalars(select(Site).where(Site.tenant_id == ctx.tenant_id)))
    sites = [s for s in sites if s.site_id in ctx.site_ids]
    count = lambda model, *where: db.scalar(select(func.count()).select_from(model).where(model.tenant_id == ctx.tenant_id, *where)) or 0  # noqa: E731
    workers = count(Worker, Worker.status == "active")
    standards = count(WorkStandard, WorkStandard.effective_to.is_(None))
    history = count(DemandBucket)
    supplied = count(SuppliedForecast, SuppliedForecast.state == "active")
    rosters = count(RosterVersion)
    from app.models.billing import TenantSetup
    from app.models.canonical import LabourCostRule
    from app.models.identity import KioskDevice
    setup = db.get(TenantSetup, ctx.tenant_id)
    rates = count(LabourCostRule)
    devices = count(KioskDevice, KioskDevice.status == "active")

    def step(key, title, done, detail, todo, link, optional=False):
        return {"key": key, "title": title, "state": "done" if done else "todo", "detail": detail if done else todo, "link": link, "optional": optional}
    steps = [
        step("organisation", "Your organisation", bool(t and t.name), f"{t.name}" if t else "", "An administrator at Ensemble Solutions creates your organisation.", None),
        step("sites", "Sites and time zones", len(sites) > 0, f"{len(sites)} site(s): " + ", ".join(f"{s.name} ({s.timezone})" for s in sites[:4]), "No site is set up yet. Ask your administrator to add your first site with its time zone.", None),
        step("staff", "Staff", workers > 0, f"{workers} active people loaded", "Load your people from a spreadsheet (download the template, fill it in, upload it).", "/data?tab=upload&class=master&entity=workers"),
        step("standards", "Work standards", standards > 0, f"{standards} activities have a work standard", "Tell Tempo how long each activity takes per unit. Everything about workload depends on these.", "/data?tab=upload&class=master&entity=work_standards"),
        step("workload", "Workload", history > 0 or supplied > 0, ("Workload history is loaded" if history else "") + (" · " if history and supplied else "") + ("A supplied forecast is loaded" if supplied else ""),
             "Load past workload (totals or individual events), or a forecast of upcoming work, so Tempo can plan.", "/data?tab=upload&class=bulk"),
        step("rates", "Labour rates", rates > 0, f"{rates} rate(s) set", "Optional: add hourly rates so planned cost can be shown. Without them cost is shown as unavailable, never zero.", "/data?tab=upload&class=master&entity=rates", optional=True),
        step("attendance", "Attendance", bool(setup and setup.attendance_choice) or devices > 0, ("A kiosk is set up" if devices else {"tempo_kiosk": "You chose Tempo's kiosk", "external": "Attendance comes from another system", "later": "Decide later"}.get(setup.attendance_choice if setup else "", "")),
             "Choose how people will clock in: Tempo's kiosk, or another system.", "/setup", optional=True),
        step("roster", "First roster", rosters > 0, f"{rosters} roster version(s) created", "Generate a draft roster from the workload, adjust it and publish it.", "/roster"),
    ]
    skipped = set((setup.skipped if setup else []) or [])
    for st in steps:
        if st["state"] == "todo" and st["optional"] and st["key"] in skipped:
            st["state"], st["detail"] = "skipped", "Skipped for now"
    required = [s for s in steps if not s["optional"]]
    done = sum(1 for s in steps if s["state"] == "done")
    nxt = next((s for s in steps if s["state"] == "todo" and not s["optional"]), None) or next((s for s in steps if s["state"] == "todo"), None)
    return {"steps": steps, "done": done, "total": len(steps), "next": nxt["key"] if nxt else None, "complete": all(s["state"] == "done" for s in required)}


# ------------------------------------------------------------------------------------------------------------------ resumable wizard
class SetupState(BaseModel):
    current_step: str | None = Field(default=None, pattern="^(organisation|sites|staff|standards|workload|rates|attendance|roster)$")
    attendance_choice: str | None = Field(default=None, pattern="^(tempo_kiosk|external|later)$")
    skipped: list[str] | None = None


def _state_out(row) -> dict:
    return {"current_step": row.current_step if row else "sites", "attendance_choice": row.attendance_choice if row else None, "skipped": list(row.skipped or []) if row else []}


@router.get("/setup/state")
def get_setup_state(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    from app.models.billing import TenantSetup
    return _state_out(db.get(TenantSetup, ctx.tenant_id))


@router.put("/setup/state")
def put_setup_state(body: SetupState, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Remember where this organisation is in setup. Safe to repeat; which steps are done is never stored here, it is read from the data."""
    from app.models.billing import TenantSetup
    if not ctx.has_permission(PERM):
        raise AuthForbidden(f"caller lacks {PERM}")
    row = db.get(TenantSetup, ctx.tenant_id)
    if row is None:
        row = TenantSetup(tenant_id=ctx.tenant_id, skipped=[])
        db.add(row)
    optional = {"rates", "attendance"}
    if body.current_step is not None:
        row.current_step = body.current_step
    if body.attendance_choice is not None:
        row.attendance_choice = body.attendance_choice
    if body.skipped is not None:
        row.skipped = sorted(set(body.skipped) & optional)
    row.updated_by, row.updated_at = ctx.user_id, datetime.now(timezone.utc)
    db.flush()
    return _state_out(row)


class SiteIn(BaseModel):
    site_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    name: str = Field(min_length=1, max_length=200)
    timezone: str
    operating_mode: str = Field(default="standalone", pattern="^(standalone|overlay)$")


@router.post("/setup/sites", status_code=201)
def setup_site(body: SiteIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Add (or rename) one site during setup. Repeating the request never makes a second site. The same rules as the sites upload apply:
    needs the configure permission, a time zone cannot be changed once the site exists, the plan's site limit is respected, and the creator is given access."""
    from zoneinfo import ZoneInfo
    from sqlalchemy import text as _t
    from app.core import subscription as _sub
    from app.db import bind_sites
    from app.models.identity import TempoUser, UserSiteGrant
    if not ctx.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure")
    try:
        ZoneInfo(body.timezone)
    except Exception:  # noqa: BLE001
        raise ScopeError(f"'{body.timezone}' is not a time zone name. Use a name like Australia/Melbourne.") from None
    db.execute(_t("SELECT set_config('app.site_scope', '*', true)"))
    try:
        x = db.get(Site, (ctx.tenant_id, body.site_id))
        created = x is None
        if created:
            _sub.require_site_capacity(db, ctx.tenant_id, 1)
            db.add(Site(tenant_id=ctx.tenant_id, site_id=body.site_id, name=body.name, timezone=body.timezone, operating_mode=body.operating_mode))
            db.flush()
            if db.get(TempoUser, ctx.user_id) is not None and not db.scalar(select(UserSiteGrant.id).where(UserSiteGrant.user_id == ctx.user_id, UserSiteGrant.tenant_id == ctx.tenant_id, UserSiteGrant.site_id == body.site_id)):
                db.add(UserSiteGrant(user_id=ctx.user_id, tenant_id=ctx.tenant_id, site_id=body.site_id))
        else:
            if x.timezone != body.timezone:
                raise ScopeError(f"site '{body.site_id}' already uses {x.timezone}; a site's time zone cannot be changed because it would move its history")
            x.name, x.operating_mode = body.name, body.operating_mode
        db.flush()
    finally:
        bind_sites(db, list(ctx.site_ids) + ([body.site_id] if body.site_id not in ctx.site_ids else []))
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="setup.site", decision="allowed", reason_code="created" if created else "updated", session_ref=body.site_id, correlation_id=ctx.correlation_id)
    return {"site_id": body.site_id, "created": created}
