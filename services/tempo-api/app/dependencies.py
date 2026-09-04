"""Shared FastAPI dependencies: request scope, DB session, idempotency key.

§5.3 specifies OIDC/OAuth2 short-lived JWTs between Prime, Tempo and Maestro.
Standing up a real IdP is out of Phase 0's scope (see docs/roadmap.md) — this
scaffold instead requires the caller to present the already-validated scope
as a header, so every downstream handler still goes through the same
RequestContext enforcement path a real token verifier would populate. This
is a Phase 0 stand-in, not a security control, and must not reach production
(tracked as OD-01 in the Integration Spec).
"""
from __future__ import annotations

import json
from collections.abc import Generator

from fastapi import Header
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.errors import ScopeError
from app.schemas.tenancy import RequestContext


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_request_context(x_tempo_context: str | None = Header(default=None)) -> RequestContext:
    if not x_tempo_context:
        raise ScopeError("X-Tempo-Context header is required and must carry tenant/business scope")
    try:
        raw = json.loads(x_tempo_context)
    except json.JSONDecodeError as exc:
        raise ScopeError(f"X-Tempo-Context is not valid JSON: {exc}") from exc
    try:
        context = RequestContext(**raw)
    except ValidationError as exc:
        raise ScopeError(f"request scope failed validation: {exc}") from exc
    if not context.site_ids and not context.customer_ids:
        # DP-08 / INT-003: never default to a tenant-wide view.
        raise ScopeError("at least one of site_ids or customer_ids must be specified")
    return context


def get_idempotency_key(idempotency_key: str | None = Header(default=None)) -> str | None:
    return idempotency_key


def require_idempotency_key(idempotency_key: str | None = Header(default=None)) -> str:
    if not idempotency_key:
        raise ScopeError("Idempotency-Key header is required for this operation")
    return idempotency_key
