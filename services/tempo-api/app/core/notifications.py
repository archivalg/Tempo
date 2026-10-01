"""In-app notifications. Recipients are resolved from Tempo's own role and site grants, never from caller input,
and nobody is told about something they could not open (site scope and permission are both required)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import permissions_for_roles
from app.models.identity import TenantMembership, UserRoleAssignment, UserSiteGrant
from app.models.rosters import Notification


def recipients(db: Session, tenant_id: str, site_id: str, permission: str, exclude: set[str] | None = None) -> list[str]:
    on_site = set(db.scalars(select(UserSiteGrant.user_id).where(UserSiteGrant.tenant_id == tenant_id, UserSiteGrant.site_id == site_id)))
    active = set(db.scalars(select(TenantMembership.user_id).where(TenantMembership.tenant_id == tenant_id, TenantMembership.status == "active")))
    roles: dict[str, list[str]] = {}
    for uid, role in db.execute(select(UserRoleAssignment.user_id, UserRoleAssignment.role).where(UserRoleAssignment.tenant_id == tenant_id)):
        roles.setdefault(uid, []).append(role)
    return sorted(u for u in on_site & active if permission in permissions_for_roles(roles.get(u, [])) and u not in (exclude or set()))


def notify(db: Session, tenant_id: str, user_ids: list[str], *, kind: str, title: str, body: str = "", link: str | None = None,
           site_id: str | None = None, dedup_key: str, severity: str = "info") -> int:
    """Adds one notice per user; a user who already has this dedup_key is skipped. Returns how many were added."""
    have = set(db.scalars(select(Notification.user_id).where(Notification.tenant_id == tenant_id, Notification.dedup_key == dedup_key, Notification.user_id.in_(user_ids or [""]))))
    n = 0
    for uid in user_ids:
        if uid in have:
            continue
        db.add(Notification(tenant_id=tenant_id, user_id=uid, kind=kind, severity=severity, title=title, body=body, link=link, site_id=site_id, dedup_key=dedup_key))
        n += 1
    return n


def serialise(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body, "link": n.link, "site_id": n.site_id, "created_at": n.created_at, "read_at": n.read_at}
