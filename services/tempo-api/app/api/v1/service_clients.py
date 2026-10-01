"""Tenant admins issue, rotate and revoke API credentials for the ingestion channel. The secret is returned once and never again."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth, service_auth
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, RunNotFound, ScopeError
from app.models.identity import ServiceClient
from app.schemas.tenancy import RequestContext

router = APIRouter(prefix="/admin/api-credentials", tags=["admin"])


def _need(ctx: RequestContext) -> None:
    if not ctx.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure")


def _out(c: ServiceClient) -> dict:
    return {"id": c.client_id, "name": c.name, "prefix": f"{service_auth.PREFIX}{c.credential_prefix}", "scopes": c.scopes, "site_ids": c.site_ids, "status": c.status,
            "expires_at": c.expires_at, "last_used_at": c.last_used_at, "rotated_at": c.rotated_at, "created_at": c.created_at}


class Create(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    site_ids: list[str] | None = None
    valid_days: int = Field(default=90, ge=1, le=service_auth.MAX_DAYS)


@router.get("")
def list_credentials(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    _need(ctx)
    return [_out(c) for c in db.scalars(select(ServiceClient).where(ServiceClient.tenant_id == ctx.tenant_id).order_by(ServiceClient.created_at.desc()))]


@router.post("", status_code=201)
def create(body: Create, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx)
    if body.site_ids is not None and not set(body.site_ids) <= set(ctx.site_ids):
        raise ScopeError("a credential can only cover sites inside your own access")
    c, secret = service_auth.issue(db, ctx.tenant_id, body.name, body.site_ids, body.valid_days)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="credential.create", decision="allowed", session_ref=c.client_id, correlation_id=ctx.correlation_id)
    return {**_out(c), "secret": secret, "note": "Copy this now. It is not stored and cannot be shown again."}


def _get(db: Session, ctx: RequestContext, cid: str) -> ServiceClient:
    c = db.get(ServiceClient, cid)
    if c is None or c.tenant_id != ctx.tenant_id:
        raise RunNotFound("credential not found")
    return c


@router.post("/{credential_id}/rotate")
def rotate(credential_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx)
    c = _get(db, ctx, credential_id)
    if c.status != "active":
        raise ScopeError("a revoked credential cannot be rotated — create a new one")
    secret = service_auth.rotate(c)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="credential.rotate", decision="allowed", session_ref=c.client_id, correlation_id=ctx.correlation_id)
    return {**_out(c), "secret": secret, "note": "The previous secret no longer works. Copy this one now."}


@router.post("/{credential_id}/revoke")
def revoke(credential_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx)
    c = _get(db, ctx, credential_id)
    c.status = "revoked"
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="credential.revoke", decision="allowed", session_ref=c.client_id, correlation_id=ctx.correlation_id)
    return _out(c)
