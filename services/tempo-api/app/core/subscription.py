"""Plans, allowances and entitlement checks (roadmap M6-PLAN / M6-MANUAL).

Rules made explicit here:
* A tenant with no subscription record is *unmanaged*: no commercial limits apply and the screens say so. Existing and demo tenants stay usable.
* Active workers = worker records with status 'active' in the tenant right now, counted once however many sites or employment types
  (agency/labour-hire included, inactive excluded). It is shown to the customer next to the allowance.
* An allowance warning never blocks attendance or silently changes a band. Only the licensed *site count* is a hard limit, and only
  when adding a site; the message says how to ask for more.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import PolicyConflict
from app.models.billing import PlanDefinition, SubscriptionEvent, TenantSubscription
from app.models.canonical import Worker
from app.models.directory import Site

BANDS = {"250": (250, "up to 250 active workers"), "500": (500, "251–500 active workers"), "1000": (1000, "501–1,000 active workers"), "1000+": (None, "more than 1,000 active workers")}
MANUAL_KINDS = ("contract", "pilot", "demo", "complimentary")
NEAR = 0.9


def now() -> datetime:
    return datetime.now(timezone.utc)


def active_workers(db: Session, tenant_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Worker).where(Worker.tenant_id == tenant_id, Worker.status == "active")) or 0


def sites_in_use(db: Session, tenant_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Site).where(Site.tenant_id == tenant_id)) or 0


def plan(db: Session, key: str, version: int) -> PlanDefinition | None:
    return db.scalar(select(PlanDefinition).where(PlanDefinition.plan_key == key, PlanDefinition.version == version))


def effective_status(sub: TenantSubscription) -> str:
    if sub.status == "active" and sub.expires_at is not None and sub.expires_at.astimezone(timezone.utc) <= now():
        return "expired"
    return sub.status


def event(db: Session, tenant_id: str, actor: str, action: str, reason: str = "", detail: dict | None = None) -> None:
    db.add(SubscriptionEvent(tenant_id=tenant_id, actor=actor, action=action, reason=reason, detail=detail or {}))


def describe(db: Session, tenant_id: str) -> dict:
    """What the customer sees about their plan and allowance."""
    sub = db.get(TenantSubscription, tenant_id)
    workers, sites = active_workers(db, tenant_id), sites_in_use(db, tenant_id)
    if sub is None:
        return {"managed": False, "message": "No plan is recorded for this organisation, so no commercial limits are applied.", "active_workers": workers, "sites_in_use": sites}
    p = plan(db, sub.plan_key, sub.plan_version)
    cap, band_label = BANDS[sub.worker_band]
    state = "ok" if cap is None or workers <= cap * NEAR else ("near" if workers <= cap else "over")
    return {"managed": True, "plan": {"key": sub.plan_key, "version": sub.plan_version, "name": p.name if p else sub.plan_key, "approved": bool(p and p.status == "approved"),
                                       "indicative_price_note": "Prices shown to platform staff are indicative proposals until a plan version is approved."},
            "billing_source": sub.billing_source, "manual_kind": sub.manual_kind, "status": effective_status(sub), "effective_from": sub.effective_from, "expires_at": sub.expires_at,
            "licensed_sites": sub.licensed_sites, "sites_in_use": sites, "worker_band": sub.worker_band, "worker_allowance": cap, "worker_band_label": band_label,
            "active_workers": workers, "allowance_state": state,
            "allowance_message": {"ok": "Within your workforce allowance.", "near": "You are close to your workforce allowance. Contact us to move to the next band.",
                                  "over": "You are over your workforce allowance. Nothing has been blocked or charged; contact us to agree the right band."}[state],
            "measurement": "Active workers = people marked active in Tempo today, counted once across all sites, including agency and labour-hire; inactive people are not counted."}


def require_site_capacity(db: Session, tenant_id: str, adding: int) -> None:
    sub = db.get(TenantSubscription, tenant_id)
    if sub is None or effective_status(sub) != "active":
        return
    if sites_in_use(db, tenant_id) + adding > sub.licensed_sites:
        raise PolicyConflict(f"Your plan covers {sub.licensed_sites} site(s) and {sites_in_use(db, tenant_id)} are in use. Contact us to add sites.")


def entitled(db: Session, tenant_id: str, feature: str) -> bool:
    """Server-side feature check. Unmanaged tenants have every shipped feature; a managed one has what its plan version and overrides grant.
    (The plan feature matrix has not been agreed, so no shipped feature is gated on it yet.)"""
    sub = db.get(TenantSubscription, tenant_id)
    if sub is None:
        return True
    if effective_status(sub) != "active":
        return False
    p = plan(db, sub.plan_key, sub.plan_version)
    base = (p.entitlements if p else {}) or {}
    return bool({**base, **(sub.entitlements_override or {})}.get(feature, True))
