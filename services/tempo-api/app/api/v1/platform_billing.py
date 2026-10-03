"""Platform-side commercial administration (roadmap M6-PLAN / M6-MANUAL / M6-ADMIN): plan versions, manual subscriptions, tenant overview.

Stripe is not connected: a request for a 'stripe' billing source is refused rather than faked, and manual rows can never carry Stripe IDs."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import auth, subscription as sub
from app.db import bind_tenant
from app.dependencies import get_db, get_platform_principal
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.models.billing import PlanDefinition, SubscriptionEvent, TenantSubscription
from app.models.identity import PlatformAdmin, Tenant

router = APIRouter(prefix="/platform", tags=["platform"])


def _cid(request: Request) -> str:
    return getattr(request.state, "correlation_id", "n/a")


def _plan_out(p: PlanDefinition) -> dict:
    return {"id": p.id, "plan_key": p.plan_key, "version": p.version, "name": p.name, "monthly_price_per_site_aud": p.monthly_price_per_site_aud, "entitlements": p.entitlements,
            "status": p.status, "notes": p.notes, "created_by": p.created_by, "approved_by": p.approved_by, "approved_at": p.approved_at,
            "indicative": p.status != "approved"}


@router.get("/plans")
def list_plans(p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> list[dict]:
    return [_plan_out(x) for x in db.scalars(select(PlanDefinition).order_by(PlanDefinition.plan_key, PlanDefinition.version))]


class PlanIn(BaseModel):
    plan_key: str = Field(pattern="^(essentials|optimise|orchestrate|network)$")
    name: str = Field(min_length=2, max_length=60)
    monthly_price_per_site_aud: float | None = Field(default=None, ge=0, le=1_000_000)
    entitlements: dict[str, bool] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=500)


@router.post("/plans", status_code=201)
def new_plan_version(body: PlanIn, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> dict:
    """A change is always a new draft version; approved versions are never edited because tenants point at them."""
    auth.require_step_up(p)
    last = db.scalar(select(func.max(PlanDefinition.version)).where(PlanDefinition.plan_key == body.plan_key)) or 0
    x = PlanDefinition(plan_key=body.plan_key, version=last + 1, name=body.name, monthly_price_per_site_aud=body.monthly_price_per_site_aud, entitlements=body.entitlements,
                       notes=body.notes, status="draft", created_by=p.user_id)
    db.add(x)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, action="platform.plan_draft", decision="allowed", reason_code=f"{body.plan_key} v{last + 1}", correlation_id=_cid(request))
    db.flush()
    return _plan_out(x)


@router.post("/plans/{plan_id}/approve")
def approve_plan(plan_id: str, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> dict:
    auth.require_step_up(p)
    x = db.get(PlanDefinition, plan_id)
    if x is None:
        raise RunNotFound("plan version not found")
    if x.status != "draft":
        raise PolicyConflict(f"this plan version is {x.status}")
    admins = db.scalar(select(func.count()).select_from(PlatformAdmin).where(PlatformAdmin.revoked_at.is_(None))) or 0
    if x.created_by == p.user_id and admins > 1:
        raise AuthForbidden("a different platform admin must approve a plan version")
    x.status, x.approved_by, x.approved_at = "approved", p.user_id, datetime.now(timezone.utc)
    for old in db.scalars(select(PlanDefinition).where(PlanDefinition.plan_key == x.plan_key, PlanDefinition.status == "approved", PlanDefinition.id != x.id)):
        old.status = "retired"   # tenants already on it keep it; new subscriptions use the newest approved version
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, action="platform.plan_approve", decision="allowed", reason_code=f"{x.plan_key} v{x.version}", correlation_id=_cid(request))
    return _plan_out(x)


class SubscriptionIn(BaseModel):
    plan_key: str = Field(pattern="^(essentials|optimise|orchestrate|network)$")
    plan_version: int | None = None
    billing_source: str = "manual"
    manual_kind: str = Field(default="contract")
    licensed_sites: int = Field(ge=1, le=500)
    worker_band: str = Field(pattern=r"^(250|500|1000|1000\+)$")
    discount_pct: float = Field(default=0, ge=0, le=100)
    reason: str = Field(min_length=10, max_length=500)
    reference: str | None = Field(default=None, max_length=200)
    expires_at: datetime | None = None
    entitlements_override: dict[str, bool] = Field(default_factory=dict)

    @field_validator("manual_kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in sub.MANUAL_KINDS:
            raise ValueError(f"manual_kind must be one of {', '.join(sub.MANUAL_KINDS)}")
        return v


def apply_subscription(db: Session, tenant_id: str, body: SubscriptionIn, actor: str) -> TenantSubscription:
    """Create or change a tenant's manual subscription. Used by tenant creation and by later changes."""
    if body.billing_source != "manual":
        raise ScopeError("Stripe billing is not connected yet; only manual subscriptions can be recorded")
    bind_tenant(db, tenant_id)
    ver = body.plan_version
    if ver is None:
        ver = db.scalar(select(func.max(PlanDefinition.version)).where(PlanDefinition.plan_key == body.plan_key, PlanDefinition.status == "approved"))
        if ver is None:
            if body.manual_kind not in ("pilot", "demo"):
                raise PolicyConflict("no approved version of that plan exists yet; approve one first, or record this as a pilot or demo")
            ver = db.scalar(select(func.max(PlanDefinition.version)).where(PlanDefinition.plan_key == body.plan_key))
    pdef = sub.plan(db, body.plan_key, ver or 0)
    if pdef is None:
        raise RunNotFound("plan version not found")
    if pdef.status != "approved" and body.manual_kind not in ("pilot", "demo"):
        raise PolicyConflict("that plan version is not approved; only pilot or demo arrangements may use a draft plan")
    if body.expires_at is not None and body.expires_at.tzinfo is None:
        raise ScopeError("expires_at must carry a timezone offset")
    in_use = sub.sites_in_use(db, tenant_id)
    if body.licensed_sites < in_use:
        raise PolicyConflict(f"{in_use} site(s) already exist; the licensed number cannot be lower")
    cur = db.get(TenantSubscription, tenant_id)
    before = None
    if cur is None:
        cur = TenantSubscription(tenant_id=tenant_id)
        db.add(cur)
        action = "created"
    else:
        if cur.billing_source != "manual":
            raise PolicyConflict("this tenant bills through Stripe; its plan is not changed here")
        before = {k: getattr(cur, k) for k in ("plan_key", "plan_version", "licensed_sites", "worker_band", "discount_pct", "manual_kind", "expires_at")}
        action = "changed"
    cur.plan_key, cur.plan_version, cur.billing_source, cur.manual_kind = body.plan_key, ver, "manual", body.manual_kind
    cur.reason, cur.reference, cur.licensed_sites, cur.worker_band, cur.discount_pct = body.reason, body.reference, body.licensed_sites, body.worker_band, body.discount_pct
    cur.entitlements_override, cur.expires_at, cur.status = body.entitlements_override, body.expires_at, "active"
    cur.updated_by, cur.updated_at = actor, datetime.now(timezone.utc)
    if before is not None:
        before = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in before.items()}
    sub.event(db, tenant_id, actor, action, body.reason, {"plan": f"{body.plan_key} v{ver}", "licensed_sites": body.licensed_sites, "worker_band": body.worker_band, "manual_kind": body.manual_kind,
                                                          "reference": body.reference, "before": before})
    db.flush()
    return cur


@router.put("/tenants/{tenant_id}/subscription")
def set_subscription(tenant_id: str, body: SubscriptionIn, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> dict:
    auth.require_step_up(p)
    if db.get(Tenant, tenant_id) is None:
        raise RunNotFound("tenant not found")
    s = apply_subscription(db, tenant_id, body, p.user_id)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=tenant_id, action="platform.subscription_set", decision="allowed", reason_code=body.reason[:100], correlation_id=_cid(request))
    return sub.describe(db, tenant_id)


@router.get("/tenant-overview")
def tenant_overview(q: str | None = Query(default=None, max_length=80), p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> list[dict]:
    """One row per tenant for support: lifecycle, plan, allowance, billing source. Counts only; no tenant business data."""
    out = []
    for t in db.scalars(select(Tenant).order_by(Tenant.created_at)):
        if q and q.lower() not in t.name.lower() and q.lower() not in t.tenant_id.lower():
            continue
        bind_tenant(db, t.tenant_id)
        d = sub.describe(db, t.tenant_id)
        out.append({"tenant_id": t.tenant_id, "name": t.name, "status": t.status, "created_at": t.created_at, "managed": d["managed"],
                    "plan": d.get("plan", {}).get("name") if d["managed"] else None, "billing_source": d.get("billing_source"), "manual_kind": d.get("manual_kind"),
                    "subscription_status": d.get("status"), "licensed_sites": d.get("licensed_sites"), "sites_in_use": d["sites_in_use"], "worker_band": d.get("worker_band"),
                    "active_workers": d["active_workers"], "allowance_state": d.get("allowance_state"), "expires_at": d.get("expires_at")})
    from app.db import begin_auth_lookup
    begin_auth_lookup(db)
    return out


@router.get("/tenants/{tenant_id}/subscription-history")
def subscription_history(tenant_id: str, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> list[dict]:
    if db.get(Tenant, tenant_id) is None:
        raise RunNotFound("tenant not found")
    bind_tenant(db, tenant_id)
    rows = [{"at": e.at, "actor": e.actor, "action": e.action, "reason": e.reason, "detail": e.detail} for e in db.scalars(
        select(SubscriptionEvent).where(SubscriptionEvent.tenant_id == tenant_id).order_by(SubscriptionEvent.at.desc()).limit(100))]
    from app.db import begin_auth_lookup
    begin_auth_lookup(db)
    return rows
