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

from app.config import settings
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
        from app.core import password_login as pl

        token = pl.create_invitation(db, user, f"operator:{operator}") if user.password_hash is None else None
        db.commit()
        how = "IdP subject" if subject else "verified email invitation (links at first verified login)"
        print(f"platform admin created for {how}: user_id={user.user_id}. No password was set.")
        if token:
            print(f"One-time invitation (shown once, expires in {settings.invite_ttl_hours}h): /invite?token={token}")
            print("Open it in the browser over HTTPS, choose a username and password, then enrol the authenticator app.")
        return 0
    finally:
        db.close()


def _user_command(args) -> int:
    import getpass
    from datetime import datetime, timezone

    from app.core import passwords, password_login as pl

    db = db_module.SessionLocal()
    try:
        user = pl.find_user(db, pl.normalise(args.username))
        if user is None:
            print("no such user", file=sys.stderr)
            return 2
        if args.cmd == "unlock-user":
            user.locked_until, user.failed_logins = None, 0
            auth.audit(db, actor_type="operator", actor_id=args.operator, action="user.unlock", decision="allowed", session_ref=user.user_id)
            db.commit()
            print("unlocked")
            return 0
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat password: "):
            print("passwords differ", file=sys.stderr)
            return 2
        problems = passwords.policy_problems(pw, username=user.username, email=user.email)
        if problems:
            print("rejected: " + "; ".join(problems), file=sys.stderr)
            return 2
        user.username = user.username or (user.email or "").lower() or None
        user.password_hash, user.password_changed_at, user.failed_logins, user.locked_until = passwords.hash_password(pw), datetime.now(timezone.utc), 0, None
        auth.revoke_user_everywhere(db, user.user_id, reason="operator_set_password")
        auth.audit(db, actor_type="operator", actor_id=args.operator, action="password.set_by_operator", decision="allowed", session_ref=user.user_id)
        db.commit()
        print(f"password set for {user.username}. Existing sessions were revoked.")
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
    d = sub.add_parser("bootstrap-ensemble-demo", help="seed the synthetic Ensemble Solutions tenant (non-production only)")
    d.add_argument("--reset", action="store_true", help="wipe the demo tenant first and re-seed anchored to now")
    d.add_argument("--secrets-dir", help="where the demo kiosk enrolment code / PINs are written (mode 600); default ~/.config/tempo-demo")
    sub.add_parser("reset-ensemble-demo", help="delete the synthetic demo tenant (non-production only)")
    sp = sub.add_parser("set-password", help="set or reset a user's password from a hidden prompt (never printed or logged)")
    sp.add_argument("--username", required=True, help="username or email of an existing user")
    sp.add_argument("--operator", required=True)
    ul = sub.add_parser("unlock-user", help="clear a lockout")
    ul.add_argument("--username", required=True)
    ul.add_argument("--operator", required=True)
    sub.add_parser("demo-status", help="show the demo seed manifest")
    args = ap.parse_args(argv)
    if args.cmd == "bootstrap-platform-admin":
        if not args.confirm_verified_identity:
            print("refused: pass --confirm-verified-identity after verifying the identity with the IdP", file=sys.stderr)
            return 2
        return bootstrap_platform_admin(subject=args.subject, email=args.email, operator=args.operator)
    if args.cmd in ("set-password", "unlock-user"):
        return _user_command(args)
    if args.cmd in ("bootstrap-ensemble-demo", "reset-ensemble-demo", "demo-status"):
        import json

        from app.demo import ensemble

        if args.cmd == "bootstrap-ensemble-demo":
            print(json.dumps(ensemble.bootstrap(reset_first=args.reset, secrets_dir=args.secrets_dir), indent=2, default=str))
        elif args.cmd == "reset-ensemble-demo":
            db = db_module.SessionLocal()
            try:
                ensemble.reset(db)
            finally:
                db.close()
            print("demo tenant removed")
        else:
            db = db_module.SessionLocal()
            try:
                print(json.dumps(ensemble.status(db), indent=2, default=str))
            finally:
                db.close()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
