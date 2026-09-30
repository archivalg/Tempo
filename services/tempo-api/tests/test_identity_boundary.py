"""Gate 1 evidence: identity is server-derived; forged/stale/revoked credentials fail closed."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, text

from app.config import settings
from app.core import auth
from app.models.identity import SecurityAuditEvent, TempoUser, UserSession

from .conftest import context_header, make_principal

URL = "/v1/data-readiness"
Q = {"capability": "optimize.roster"}


def _forged_ctx(tenant="ten_victim", roles=("tenant_admin",)):
    return json.dumps({"tenant_id": tenant, "site_ids": ["s1"], "customer_ids": ["c1"], "user_id": "attacker",
                       "roles": list(roles), "purpose": "x", "correlation_id": "c"})


def test_forged_x_tempo_context_alone_is_rejected(client):
    r = client.get(URL, params=Q, headers={"X-Tempo-Context": _forged_ctx()})
    assert r.status_code == 401


def test_forged_context_cannot_change_tenant_or_roles_of_a_valid_token(client):
    token = make_principal(client.session_local, tenant_id="ten_a", roles=("analyst",))
    h = {"Authorization": f"Bearer {token}", "X-Tempo-Context": _forged_ctx("ten_b", ("tenant_admin",))}
    r = client.get("/v1/me/access", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "ten_a" and body["roles"] == ["analyst"]
    assert "labour.configure" not in body["permissions"]


def test_tenant_selector_is_checked_against_memberships(client):
    token = make_principal(client.session_local, tenant_id="ten_a")
    r = client.get("/v1/me/access", headers={"Authorization": f"Bearer {token}", "X-Tempo-Tenant": "ten_b"})
    assert r.status_code == 403


def test_tampered_and_unsigned_tokens_rejected(client):
    token = make_principal(client.session_local)
    claims = jwt.decode(token, options={"verify_signature": False})
    for bad in (
        jwt.encode(claims, "wrong-key-wrong-key-wrong-key-wrong", algorithm="HS256"),
        jwt.encode(claims, key=None, algorithm="none"),
        token[:-2] + ("AA" if not token.endswith("AA") else "BB"),
    ):
        assert client.get("/v1/me/access", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_expired_token_rejected(client):
    token = make_principal(client.session_local)
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    expired = jwt.encode(claims, auth._signing_key(), algorithm="HS256")
    assert client.get("/v1/me/access", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_revoked_session_blocks_access_immediately(client):
    token = make_principal(client.session_local)
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/me/access", headers=h).status_code == 200
    sid = jwt.decode(token, options={"verify_signature": False})["sid"]
    with client.session_local() as s:
        s.get(UserSession, sid).revoked_at = datetime.now(timezone.utc)
        s.commit()
    assert client.get("/v1/me/access", headers=h).status_code == 401


def test_token_version_bump_revokes_all_outstanding_tokens(client):
    token = make_principal(client.session_local, user_id="usr_tv")
    with client.session_local() as s:
        auth.revoke_user_everywhere(s, "usr_tv", reason="test")
        s.commit()
    assert client.get("/v1/me/access", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_removed_grant_takes_effect_on_next_request(client):
    token = make_principal(client.session_local, user_id="usr_g", site_ids=("site_x",), customer_ids=())
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/me/access", headers=h).json()["site_ids"] == ["site_x"]
    with client.session_local() as s:
        s.execute(text("DELETE FROM user_site_grant WHERE user_id='usr_g'"))
        s.commit()
    assert client.get("/v1/me/access", headers=h).json()["site_ids"] == []
    assert client.get(URL, params=Q, headers=h).status_code == 400  # no grants => denied, never widened


def test_admin_without_mfa_loses_admin_permissions(client):
    token = make_principal(client.session_local, roles=("tenant_admin",), mfa=False)
    body = client.get("/v1/me/access", headers={"Authorization": f"Bearer {token}"}).json()
    assert "labour.configure" not in body["permissions"] and body["mfa_verified"] is False


def test_refresh_rotation_and_replay_revokes_family(client):
    with client.session_local() as s:
        s.add(TempoUser(user_id="usr_r", external_subject="sub_r"))
        s.flush()
        first = auth.create_session(s, s.get(TempoUser, "usr_r"), mfa=False, auth_method="test")
        s.commit()
        second = auth.rotate_refresh(s, first.refresh_token)
        s.commit()
        assert second.refresh_token != first.refresh_token
        try:
            auth.rotate_refresh(s, first.refresh_token)  # replay of a rotated credential
            raise AssertionError("replay should fail")
        except Exception as exc:  # AuthInvalid
            assert "no longer valid" in str(exc)
        with client.session_local() as s2:
            fam = s2.scalars(select(UserSession).where(UserSession.user_id == "usr_r")).all()
            assert all(r.revoked_at is not None for r in fam)
            assert s2.scalar(select(SecurityAuditEvent).where(SecurityAuditEvent.action == "session.family_revoked"))


def test_cookie_session_requires_csrf_but_bearer_does_not(client, monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)  # TestClient speaks plain http
    r = client.post("/v1/auth/dev-login", json={"subject": "sub_c"})
    assert r.status_code == 403  # unknown identity: no self-signup
    with client.session_local() as s:
        s.add(TempoUser(user_id="usr_c", external_subject="sub_c"))
        s.commit()
    r = client.post("/v1/auth/dev-login", json={"subject": "sub_c"})
    assert r.status_code == 200 and r.json()["production_authentication"] is False
    # cookie now set on the client; unsafe method without CSRF header is refused
    assert client.post("/v1/auth/logout").status_code == 403
    ok = client.post("/v1/auth/logout", headers={"X-CSRF-Token": r.json()["csrf_token"]})
    assert ok.status_code == 200
    client.cookies.clear()


def test_dev_idp_disabled_outside_local(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_idp_enabled", False)
    assert client.post("/v1/auth/dev-login", json={"subject": "x"}).status_code == 401
    monkeypatch.setattr(settings, "dev_idp_enabled", True)
    monkeypatch.setattr(settings, "env", "production")
    assert client.post("/v1/auth/dev-login", json={"subject": "x"}).status_code == 401


def test_production_start_rejects_insecure_defaults():
    import pytest
    from app.config import Settings, validate_settings
    with pytest.raises(RuntimeError, match="insecure configuration"):
        validate_settings(Settings(env="production"))
    with pytest.raises(RuntimeError):
        validate_settings(Settings(env="uat", dev_idp_enabled=True))
    with pytest.raises(RuntimeError, match="only permitted"):
        validate_settings(Settings(env="staging", dev_idp_enabled=True))


def test_dev_identity_list_exists_only_when_the_dev_idp_is_enabled(client, monkeypatch):
    with client.session_local() as s:
        s.add(TempoUser(user_id="usr_demo", external_subject="dev|x", email="x@demo.tempo.invalid", display_name="Demo X (synthetic)"))
        s.add(TempoUser(user_id="usr_real", external_subject="idp|real", email="real@example.com"))
        s.commit()
    ok = client.get("/v1/auth/dev-identities")
    assert ok.status_code == 200 and [i["email"] for i in ok.json()] == ["x@demo.tempo.invalid"]  # never a real user
    monkeypatch.setattr(settings, "dev_idp_enabled", False)
    assert client.get("/v1/auth/dev-identities").status_code == 401
