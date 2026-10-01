"""Service credentials for the API ingestion channel (SEC-22). A credential is `tsc_<prefix>.<secret>`; only a SHA-256 digest of the
secret is stored (the secret is high-entropy, so a fast hash is appropriate) and it is shown once. A credential carries exactly one
role (`integration_import`), a tenant, an optional site list and an expiry; it can be rotated and revoked."""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth
from app.db import begin_auth_lookup, bind_sites, bind_tenant
from app.errors import AuthForbidden, AuthInvalid
from app.models.identity import ServiceClient
from app.schemas.tenancy import RequestContext

PREFIX = "tsc_"
SCOPE = "labour.data.import"
MAX_DAYS = 365


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def issue(db: Session, tenant_id: str, name: str, site_ids: list[str] | None, days: int) -> tuple[ServiceClient, str]:
    prefix, secret = secrets.token_hex(4), secrets.token_urlsafe(32)
    c = ServiceClient(tenant_id=tenant_id, name=name[:120], credential_prefix=prefix, credential_hash=auth.digest(secret), scopes=[SCOPE],
                      site_ids=sorted(set(site_ids)) if site_ids else None, expires_at=_now() + timedelta(days=min(max(days, 1), MAX_DAYS)))
    db.add(c)
    db.flush()
    return c, f"{PREFIX}{prefix}.{secret}"


def rotate(c: ServiceClient) -> str:
    secret = secrets.token_urlsafe(32)
    c.credential_prefix, c.credential_hash, c.rotated_at = secrets.token_hex(4), auth.digest(secret), _now()
    return f"{PREFIX}{c.credential_prefix}.{secret}"


def resolve(db: Session, bearer: str, correlation_id: str) -> RequestContext:
    """Bearer token → RequestContext limited to the credential's tenant and sites. Uniform failure for every bad credential."""
    bad = AuthInvalid("invalid or expired credential")
    if not bearer.startswith(PREFIX) or "." not in bearer:
        raise bad
    prefix, _, secret = bearer[len(PREFIX):].partition(".")
    begin_auth_lookup(db)
    c = db.scalar(select(ServiceClient).where(ServiceClient.credential_prefix == prefix, ServiceClient.status == "active"))
    if c is None or not hmac.compare_digest(c.credential_hash, auth.digest(secret)) or (c.expires_at and _aware(c.expires_at) <= _now()):
        raise bad
    from app.models.identity import Tenant
    t = db.get(Tenant, c.tenant_id)
    if t is None or t.status != "active":
        raise bad
    bind_tenant(db, c.tenant_id)
    from app.models.directory import Site
    all_sites = [s.site_id for s in db.scalars(select(Site).where(Site.tenant_id == c.tenant_id))]
    sites = [s for s in all_sites if (c.site_ids is None or s in c.site_ids)]
    bind_sites(db, sites)
    c.last_used_at = _now()
    return RequestContext(tenant_id=c.tenant_id, site_ids=sites, customer_ids=[], provider_id=None, user_id=f"svc:{c.client_id}", roles=["integration_import"],
                          purpose="labour.ingestion", correlation_id=correlation_id)
