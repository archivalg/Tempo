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


def _create_user(args) -> int:
    from datetime import datetime, timezone

    from app.core import passwords
    from app.core.permissions import ROLE_PERMISSION_MATRIX
    from app.db import bind_tenant
    from app.models.identity import Tenant, TenantMembership, UserCustomerGrant, UserRoleAssignment, UserSiteGrant

    pw = sys.stdin.readline().rstrip("\n")
    roles = [r for r in args.roles.split(",") if r]
    sites = [x for x in args.sites.split(",") if x]
    customers = [x for x in args.customers.split(",") if x]
    uname, email = args.username.strip().lower(), args.email.strip().lower()
    problems = passwords.policy_problems(pw, username=uname, email=email)
    if problems or not roles or not sites or any(r not in ROLE_PERMISSION_MATRIX for r in roles):
        print("rejected: " + ("; ".join(problems) or "check roles and sites"), file=sys.stderr)
        return 2
    db = db_module.SessionLocal()
    try:
        begin_auth_lookup(db)
        if db.get(Tenant, args.tenant) is None:
            print("no such tenant", file=sys.stderr)
            return 2
        if db.scalar(select(TempoUser).where((TempoUser.username == uname) | (TempoUser.email == email))) is not None:
            print("that username or email already exists", file=sys.stderr)
            return 2
        u = TempoUser(external_subject=f"pw:{uname}", email=email, username=uname, display_name=uname,
                      password_hash=passwords.hash_password(pw), password_changed_at=datetime.now(timezone.utc))
        db.add(u)
        db.flush()
        auth.audit(db, actor_type="operator", actor_id=args.operator, tenant_id=args.tenant, action="user.create_cli", decision="allowed", session_ref=u.user_id,
                   reason_code=",".join(sorted(roles)))
        bind_tenant(db, args.tenant)
        db.add(TenantMembership(user_id=u.user_id, tenant_id=args.tenant, is_default=True, invitation_source=f"operator:{args.operator}"))
        for r in roles:
            db.add(UserRoleAssignment(user_id=u.user_id, tenant_id=args.tenant, role=r))
        for x in sites:
            db.add(UserSiteGrant(user_id=u.user_id, tenant_id=args.tenant, site_id=x))
        for x in customers:
            db.add(UserCustomerGrant(user_id=u.user_id, tenant_id=args.tenant, customer_id=x))
        db.commit()
        print(f"created {uname} in {args.tenant} with roles {','.join(roles)}")
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
    cu = sub.add_parser("create-user", help="create a user in a tenant with an initial password read from stdin (never an argument)")
    cu.add_argument("--tenant", required=True)
    cu.add_argument("--email", required=True)
    cu.add_argument("--username", required=True)
    cu.add_argument("--roles", required=True, help="comma-separated role names")
    cu.add_argument("--sites", required=True, help="comma-separated site ids")
    cu.add_argument("--customers", default="", help="comma-separated customer ids")
    cu.add_argument("--password-stdin", action="store_true", required=True)
    cu.add_argument("--operator", required=True)
    sm = sub.add_parser("set-smtp", help="set the platform SMTP account; the password is read from stdin (never an argument) and stored encrypted")
    sm.add_argument("--host", required=True)
    sm.add_argument("--port", type=int, default=587)
    sm.add_argument("--security", choices=("starttls", "ssl", "none"), default="starttls")
    sm.add_argument("--username", required=True)
    sm.add_argument("--from-email", required=True)
    sm.add_argument("--from-name", default="Tempo")
    sm.add_argument("--password-stdin", action="store_true", required=True)
    sm.add_argument("--operator", required=True)
    sub.add_parser("run-notification-jobs", help="run one cycle of the notification job loop (reminders, pushes, retries, receipts)")
    sub.add_parser("demo-status", help="show the demo seed manifest")
    args = ap.parse_args(argv)
    if args.cmd == "bootstrap-platform-admin":
        if not args.confirm_verified_identity:
            print("refused: pass --confirm-verified-identity after verifying the identity with the IdP", file=sys.stderr)
            return 2
        return bootstrap_platform_admin(subject=args.subject, email=args.email, operator=args.operator)
    if args.cmd == "set-smtp":
        from datetime import datetime, timezone

        from app.core import email as mail
        from app.models.billing import SmtpConfig

        pw = sys.stdin.readline().rstrip("\n")
        if not pw:
            print("no password on stdin", file=sys.stderr)
            return 2
        db = db_module.SessionLocal()
        try:
            begin_auth_lookup(db)
            cfg = mail.get_config(db) or SmtpConfig(id="default")
            db.add(cfg)
            cfg.enabled, cfg.host, cfg.port, cfg.security, cfg.username = True, args.host, args.port, args.security, args.username
            cfg.from_email, cfg.from_name, cfg.password_enc = args.from_email, args.from_name, mail.encrypt(pw)
            cfg.updated_by, cfg.updated_at = f"operator:{args.operator}", datetime.now(timezone.utc)
            cfg.last_test_at = cfg.last_test_ok = cfg.last_test_detail = None
            auth.audit(db, actor_type="operator", actor_id=args.operator, action="platform.email_config", decision="allowed", reason_code="enabled,password_changed,cli")
            ok, detail = mail.test_connection(db, cfg)
            db.commit()
            print(f"smtp saved (password stored encrypted). connection test: {'ok' if ok else 'FAILED'} - {detail}")
            return 0 if ok else 4
        finally:
            db.close()
    if args.cmd == "run-notification-jobs":
        import json

        from app.core.jobs import run_cycle

        print(json.dumps(run_cycle()))
        return 0
    if args.cmd == "create-user":
        return _create_user(args)
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
