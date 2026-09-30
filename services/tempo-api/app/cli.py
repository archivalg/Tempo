"""Operator commands. Run as the runtime role: `python -m app.cli <command>`.

bootstrap-platform-admin: one-time, auditable creation of the first Platform Admin from an
*explicit, IdP-verified* identity given by the operator (`--subject` or `--email`). It never
guesses an identity, creates no password, and confers nothing on a matching display name:
with `--email` the account stays a pending invitation until that exact address is presented as
verified by the identity provider. It refuses to run if any platform admin already exists.
Recovery afterwards is by a second admin: POST /v1/platform/admins (step-up required).
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app.core import auth
from app import db as db_module
from app.db import begin_auth_lookup
from app.models.identity import PlatformAdmin, TempoUser


def bootstrap_platform_admin(*, subject: str | None, email: str | None, operator: str) -> int:
    if bool(subject) == bool(email):
        print("error: provide exactly one of --subject or --email", file=sys.stderr)
        return 2
    db = db_module.SessionLocal()
    try:
        begin_auth_lookup(db)
        if db.scalar(select(PlatformAdmin).limit(1)) is not None:
            auth.audit(db, actor_type="operator", actor_id=operator, action="platform.bootstrap", decision="denied",
                       reason_code="admin_exists")
            db.commit()
            print("refused: a platform admin already exists (use a second admin to add more)", file=sys.stderr)
            return 3
        if subject:
            user = db.scalar(select(TempoUser).where(TempoUser.external_subject == subject)) or TempoUser(external_subject=subject)
        else:
            email = email.strip().lower()
            user = TempoUser(external_subject=f"pending:email:{email}", email=email)
        db.add(user)
        db.flush()
        db.add(PlatformAdmin(user_id=user.user_id, created_by=None))
        auth.audit(db, actor_type="operator", actor_id=operator, action="platform.bootstrap", decision="allowed",
                   reason_code="subject" if subject else "verified_email_invitation", session_ref=user.user_id)
        db.commit()
        how = "IdP subject" if subject else "verified email invitation (links at first verified login)"
        print(f"platform admin created for {how}: user_id={user.user_id}. No password was set.")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap-platform-admin")
    b.add_argument("--subject")
    b.add_argument("--email")
    b.add_argument("--operator", required=True, help="who is running this (recorded in the audit trail)")
    b.add_argument("--confirm-verified-identity", action="store_true",
                   help="assert the subject/email was verified with the identity provider")
    args = ap.parse_args(argv)
    if args.cmd == "bootstrap-platform-admin":
        if not args.confirm_verified_identity:
            print("refused: pass --confirm-verified-identity after verifying the identity with the IdP", file=sys.stderr)
            return 2
        return bootstrap_platform_admin(subject=args.subject, email=args.email, operator=args.operator)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
