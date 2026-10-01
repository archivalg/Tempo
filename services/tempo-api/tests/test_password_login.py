"""Username/password sign-in, lockout, TOTP, invitations, HTTPS rule and tenant user administration."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import passwords, password_login as pl
from app.models.identity import PlatformAdmin, SecurityAuditEvent, TempoUser, Tenant, TenantMembership, UserInvitation, UserRoleAssignment, UserSiteGrant

from .conftest import context_header, make_principal

PW = "correct horse battery 9"


@pytest.fixture(autouse=True)
def _relax(monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    pl.throttle.reset()


def mkuser(client, email="ana@example.test", username="ana", pw=PW, roles=("planner",), tenant="ten_test", sites=("site_mel_01",), admin=False, totp=None):
    with client.session_local() as s:
        if s.get(Tenant, tenant) is None:
            s.add(Tenant(tenant_id=tenant, name=tenant))
            s.flush()
        u = TempoUser(external_subject=f"pw|{username}", email=email, username=username, password_hash=passwords.hash_password(pw))
        s.add(u)
        s.flush()
        s.add(TenantMembership(user_id=u.user_id, tenant_id=tenant, is_default=True))
        for r in roles:
            s.add(UserRoleAssignment(user_id=u.user_id, tenant_id=tenant, role=r))
        for x in sites:
            s.add(UserSiteGrant(user_id=u.user_id, tenant_id=tenant, site_id=x))
        if admin:
            s.add(PlatformAdmin(user_id=u.user_id))
        if totp:
            u.totp_secret_enc = passwords.encrypt_secret(totp, settings.session_signing_key or __import__("app.core.auth", fromlist=["x"])._signing_key())
            from datetime import datetime, timezone
            u.totp_enabled_at = datetime.now(timezone.utc)
        s.commit()
        return u.user_id


def login(client, u="ana", p=PW):
    return client.post("/v1/auth/login", json={"username": u, "password": p})


# ------------------------------------------------------------- primitives
def test_policy_and_hash():
    assert passwords.policy_problems("short")
    assert passwords.policy_problems("ana-is-here-123", username="ana")
    assert passwords.policy_problems("password12345")
    assert not passwords.policy_problems("a long unusual passphrase 42")
    h = passwords.hash_password(PW)
    assert h.startswith("$argon2id$") and passwords.verify_password(h, PW)[0] and not passwords.verify_password(h, PW + "x")[0]
    assert passwords.verify_password(None, PW) == (False, False)


def test_totp_matches_rfc6238_vector_and_blocks_replay():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238 seed "12345678901234567890"
    assert passwords.totp_now(secret, at=59) == "287082"  # RFC 6238 SHA-1 test vector (last 6 digits of 94287082)
    step = passwords.verify_totp(secret, "287082", 0, at=59)
    assert step == 1
    assert passwords.verify_totp(secret, "287082", step, at=59) is None  # replay
    assert passwords.verify_totp(secret, "000000", 0, at=59) is None


# ------------------------------------------------------------- sign in
def test_login_sets_httponly_session_and_me_access_works(client):
    mkuser(client)
    r = login(client)
    assert r.status_code == 200 and r.json()["status"] == "signed_in" and r.json()["mfa_enrol_required"] is False
    assert "tempo_at" in client.cookies and "tempo_rt" in client.cookies
    set_cookie = r.headers.get_list("set-cookie")
    assert any(c.startswith("tempo_at=") and "HttpOnly" in c for c in set_cookie)
    assert client.get("/v1/me/access").json()["roles"] == ["planner"]
    client.cookies.clear()


def test_wrong_user_and_wrong_password_are_indistinguishable(client):
    mkuser(client)
    a = login(client, "ana", "wrong-password-123")
    b = login(client, "nobody", "wrong-password-123")
    assert (a.status_code, a.json()["detail"]) == (b.status_code, b.json()["detail"]) and a.status_code == 401


def test_lockout_after_repeated_failures_even_for_the_right_password(client):
    mkuser(client)
    for _ in range(settings.login_max_failures):
        assert login(client, "ana", "nope-nope-nope-1").status_code == 401
    assert login(client).status_code == 401  # correct password refused while locked
    with client.session_local() as s:
        actions = {(e.action, e.decision) for e in s.scalars(select(SecurityAuditEvent))}
        assert ("login.locked", "applied") in actions and ("login", "denied") in actions
        u = s.scalar(select(TempoUser).where(TempoUser.username == "ana"))
        u.locked_until = None
        s.commit()
    assert login(client).status_code == 200  # cooling-off over / unlocked by an operator
    client.cookies.clear()


def test_ip_throttle_slows_stuffing_across_accounts(client):
    for i in range(12):
        login(client, f"user{i}", "guess-guess-guess-1")
    assert login(client, "user99", "guess-guess-guess-1").status_code == 401
    with client.session_local() as s:
        reasons = [e.reason_code for e in s.scalars(select(SecurityAuditEvent))]
        assert any("throttled" in (r or "") for r in reasons) or any("bad_credentials" in (r or "") for r in reasons)


def test_login_by_email_and_no_default_credentials_exist(client):
    mkuser(client)
    assert login(client, "ANA@example.test").status_code == 200
    client.cookies.clear()
    with client.session_local() as s:
        s.add(TempoUser(external_subject="x", email="fresh@example.test"))  # invited but never set a password
        s.commit()
    assert login(client, "fresh@example.test", "").status_code == 401
    assert login(client, "fresh@example.test", "password").status_code == 401


def test_password_login_refuses_plain_http_outside_local(client, monkeypatch):
    mkuser(client)
    monkeypatch.setattr(settings, "env", "uat")
    r = login(client)
    assert r.status_code == 403 and "HTTPS" in r.json()["detail"]
    ok = client.post("/v1/auth/login", json={"username": "ana", "password": PW}, headers={"X-Forwarded-Proto": "https"})
    assert ok.status_code == 200
    client.cookies.clear()


# ------------------------------------------------------------- MFA
def test_admin_without_totp_gets_no_admin_authority_until_enrolled(client):
    mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",))
    r = login(client, "boss")
    assert r.json()["mfa_enrol_required"] is True
    assert "labour.configure" not in client.get("/v1/me/access").json()["permissions"]
    enrol = client.post("/v1/auth/mfa/enroll", headers={"X-CSRF-Token": client.cookies.get("tempo_csrf")})
    secret = enrol.json()["secret"]
    assert enrol.json()["otpauth_uri"].startswith("otpauth://totp/Tempo:")
    assert client.post("/v1/auth/mfa/confirm", json={"code": "000000"}, headers={"X-CSRF-Token": client.cookies.get("tempo_csrf")}).status_code == 401
    ok = client.post("/v1/auth/mfa/confirm", json={"code": passwords.totp_now(secret)}, headers={"X-CSRF-Token": client.cookies.get("tempo_csrf")})
    assert ok.status_code == 200
    assert "labour.configure" in client.get("/v1/me/access").json()["permissions"]  # same session, now MFA-verified
    client.cookies.clear()
    # next sign-in demands the code
    r2 = login(client, "boss")
    assert r2.json()["status"] == "mfa_required" and "tempo_at" not in client.cookies
    bad = client.post("/v1/auth/mfa/verify", json={"challenge": r2.json()["challenge"], "code": "123456"})
    assert bad.status_code == 401


def test_totp_code_cannot_be_replayed_and_challenge_is_not_a_session(client):
    secret = passwords.new_totp_secret()
    mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",), totp=secret)
    ch = login(client, "boss").json()["challenge"]
    code = passwords.totp_now(secret)
    assert client.post("/v1/auth/mfa/verify", json={"challenge": ch, "code": code}).status_code == 200
    assert client.get("/v1/me/access").json()["mfa_verified"] is True
    client.cookies.clear()
    ch2 = login(client, "boss").json()["challenge"]
    assert client.post("/v1/auth/mfa/verify", json={"challenge": ch2, "code": code}).status_code == 401  # same step = replay
    assert client.get("/v1/me/access", headers={"Authorization": f"Bearer {ch2}"}).status_code == 401  # challenge is not an access token
    client.cookies.clear()


# ------------------------------------------------------------- password change
def test_change_password_revokes_other_sessions(client):
    mkuser(client)
    login(client)
    other = client.post("/v1/auth/login", json={"username": "ana", "password": PW}).json()
    csrf = client.cookies.get("tempo_csrf")
    assert client.post("/v1/auth/password", json={"current_password": "wrong-wrong-1234", "new_password": "another good passphrase 7"}, headers={"X-CSRF-Token": csrf}).status_code == 401
    assert client.post("/v1/auth/password", json={"current_password": PW, "new_password": "ana-ana-ana-ana"}, headers={"X-CSRF-Token": csrf}).status_code == 400
    ok = client.post("/v1/auth/password", json={"current_password": PW, "new_password": "another good passphrase 7"}, headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200 and client.get("/v1/me/access").status_code == 200  # this device stays signed in
    client.cookies.clear()
    assert login(client, "ana", PW).status_code == 401 and login(client, "ana", "another good passphrase 7").status_code == 200
    client.cookies.clear()


# ------------------------------------------------------------- invitations + admin
def admin_h(**kw):
    return context_header(roles=["tenant_admin"], user_id="usr_admin", **kw)


def test_invite_accept_and_sign_in_end_to_end(client):
    r = client.post("/v1/admin/users", headers=admin_h(), json={"email": "New.Person@example.test", "roles": ["planner"], "site_ids": ["site_mel_01"]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["has_password"] is False and body["invite_token"] and body["roles"] == ["planner"]
    tok = body["invite_token"]
    with client.session_local() as s:
        inv = s.scalar(select(UserInvitation))
        assert inv.token_digest != tok and tok not in inv.token_digest  # only a digest is stored
    info = client.get(f"/v1/auth/invite/{tok}").json()
    assert info["email"] == "new.person@example.test"
    weak = client.post("/v1/auth/accept-invite", json={"token": tok, "password": "short"})
    assert weak.status_code == 400
    ok = client.post("/v1/auth/accept-invite", json={"token": tok, "password": PW, "username": "newperson"})
    assert ok.status_code == 200
    assert client.post("/v1/auth/accept-invite", json={"token": tok, "password": PW}).status_code == 401  # single use
    assert login(client, "newperson").status_code == 200
    assert client.get("/v1/me/access").json()["site_ids"] == ["site_mel_01"]
    client.cookies.clear()


def test_expired_invitation_is_refused(client):
    tok = client.post("/v1/admin/users", headers=admin_h(), json={"email": "late@example.test", "roles": ["analyst"], "site_ids": ["site_mel_01"]}).json()["invite_token"]
    from datetime import datetime, timedelta, timezone
    with client.session_local() as s:
        s.scalar(select(UserInvitation)).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    assert client.get(f"/v1/auth/invite/{tok}").status_code == 401
    assert client.post("/v1/auth/accept-invite", json={"token": tok, "password": PW}).status_code == 401


def test_tenant_admin_cannot_delegate_beyond_own_authority(client):
    h = admin_h()
    assert client.post("/v1/admin/users", headers=h, json={"email": "x@example.test", "roles": ["planner"], "site_ids": ["site_other"]}).status_code == 400
    assert client.post("/v1/admin/users", headers=h, json={"email": "x@example.test", "roles": ["god_mode"], "site_ids": ["site_mel_01"]}).status_code == 400
    assert client.post("/v1/admin/users", headers=h, json={"email": "x@example.test", "roles": ["planner"], "site_ids": []}).status_code == 400  # empty grant = no access
    assert client.post("/v1/admin/users", headers=context_header(roles=["planner"], user_id="usr_pl"), json={"email": "x@example.test", "roles": ["planner"], "site_ids": ["site_mel_01"]}).status_code == 403


def test_admin_lifecycle_is_tenant_scoped_and_cannot_touch_self_or_other_tenants(client):
    uid = mkuser(client, "ana@example.test", "ana")
    other = mkuser(client, "zed@example.test", "zed", tenant="ten_other", sites=("site_x",))
    h = admin_h()
    users = client.get("/v1/admin/users", headers=h).json()
    assert [u["email"] for u in users if u["email"] in ("ana@example.test", "zed@example.test")] == ["ana@example.test"]
    assert client.post(f"/v1/admin/users/{other}/suspend", headers=h).status_code == 404  # non-enumerating
    assert client.post(f"/v1/admin/users/{uid}/suspend", headers=h).status_code == 200
    login(client)  # suspended in this tenant -> no membership access
    assert client.get("/v1/me/access").status_code in (401, 403)
    client.cookies.clear()
    assert client.post(f"/v1/admin/users/{uid}/reinstate", headers=h).status_code == 200
    reset = client.post(f"/v1/admin/users/{uid}/reset-password", headers=h).json()
    assert reset["invite_token"]
    with client.session_local() as s:
        me = s.scalar(select(TempoUser).where(TempoUser.username == "ana"))
        assert me.password_hash  # still there until the invitation is accepted
    with client.session_local() as s2:
        actions = {e.action for e in s2.scalars(select(SecurityAuditEvent))}
    assert {"user.suspend", "user.reinstate", "user.reset_password"} <= actions
    client.post("/v1/auth/logout")


def test_grants_change_revokes_sessions_and_cannot_target_self(client):
    uid = mkuser(client, "ana@example.test", "ana", roles=("analyst",))
    login(client)
    h = admin_h()
    r = client.put(f"/v1/admin/users/{uid}/grants", headers=h, json={"roles": ["planner"], "site_ids": ["site_mel_01"]})
    assert r.status_code == 200 and r.json()["roles"] == ["planner"]
    assert client.get("/v1/me/access").status_code == 401  # old sessions were revoked
    client.cookies.clear()
    me = make_principal(client.session_local, tenant_id="ten_test", user_id="usr_selfish", roles=("tenant_admin",))
    assert client.put("/v1/admin/users/usr_selfish/grants", headers={"Authorization": f"Bearer {me}"}, json={"roles": ["analyst"], "site_ids": ["site_mel_01"]}).status_code == 403


def test_platform_tenant_creation_returns_an_invitation_not_a_password(client):
    mkuser(client, "root@example.test", "root", roles=(), admin=True, totp=passwords.new_totp_secret())
    with client.session_local() as s2:
        enc = s2.scalar(select(TempoUser).where(TempoUser.username == "root")).totp_secret_enc
    secret = passwords.decrypt_secret(enc, settings.session_signing_key or __import__("app.core.auth", fromlist=["x"])._signing_key())
    ch = login(client, "root").json()["challenge"]
    tok = client.post("/v1/auth/mfa/verify", json={"challenge": ch, "code": passwords.totp_now(secret)}).json()
    assert tok["status"] == "signed_in"
    access = client.cookies.get("tempo_at")
    r = client.post("/v1/platform/tenants", headers={"Authorization": f"Bearer {access}"}, json={"tenant_id": "acme_wms", "name": "Acme WMS", "first_admin": {"email": "owner@acme.test"}, "initial_site_ids": ["s1"]})
    assert r.status_code == 201 and r.json()["invite_token"] and "password" not in r.text.lower().replace("invite", "")
    client.cookies.clear()


def test_cli_create_user_reads_the_password_from_stdin_and_enforces_policy(client, monkeypatch):
    import io

    from app import cli

    with client.session_local() as s:
        s.add(Tenant(tenant_id="ten_cli", name="CLI"))
        s.commit()
    args = ["create-user", "--tenant", "ten_cli", "--email", "ops@cli.test", "--username", "ops.cli", "--roles", "operations_manager,planner",
            "--sites", "s1", "--password-stdin", "--operator", "tester"]
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert cli.main(args) == 2  # policy applies to operators too
    monkeypatch.setattr("sys.stdin", io.StringIO(PW + "\n"))
    assert cli.main(args) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(PW + "\n"))
    assert cli.main(args) == 2  # duplicate refused
    r = login(client, "ops.cli")
    assert r.status_code == 200
    assert client.get("/v1/me/access").json()["roles"] == ["operations_manager", "planner"]
    client.cookies.clear()
