"""Turns a verified IdP identity into a Tempo session — or refuses.

There is no self-signup and no privilege from the IdP: an identity only maps
to a Tempo user that already exists (by IdP subject) or was invited/bootstrapped
by verified email ("pending:email:<addr>", linked on first verified login).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth
from app.core.oidc import VerifiedIdentity
from app.db import begin_auth_lookup
from app.errors import AuthForbidden
from app.models.identity import TempoUser


def login_verified_identity(db: Session, ident: VerifiedIdentity, *, auth_method: str,
                            correlation_id: str, device_metadata: dict | None = None) -> auth.IssuedSession:
    begin_auth_lookup(db)
    user = db.scalar(select(TempoUser).where(TempoUser.external_subject == ident.subject))
    if user is None and ident.email and ident.email_verified:
        user = db.scalar(select(TempoUser).where(TempoUser.external_subject == f"pending:email:{ident.email}"))
        if user is not None:
            user.external_subject = ident.subject
            auth.audit(db, actor_type="user", actor_id=user.user_id, action="identity.linked",
                       decision="applied", reason_code="verified_email_invitation", correlation_id=correlation_id)
    if user is None or user.account_status != "active":
        auth.audit(db, actor_type="anonymous", actor_id=ident.subject[:64], action="login", decision="denied",
                   reason_code="no_tempo_account", correlation_id=correlation_id)
        db.commit()
        raise AuthForbidden("this identity has no Tempo access")
    if ident.email:
        user.email = ident.email
    if ident.name:
        user.display_name = ident.name
    issued = auth.create_session(db, user, mfa=ident.mfa, auth_method=auth_method, device_metadata=device_metadata)
    auth.audit(db, actor_type="user", actor_id=user.user_id, action="login", decision="allowed",
               reason_code=f"mfa={'yes' if ident.mfa else 'no'}", session_ref=issued.session_id,
               correlation_id=correlation_id)
    return issued
