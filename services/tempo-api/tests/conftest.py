"""Test harness: real PostgreSQL, real runtime role, real RLS.

* Schema is built once per session by Alembic as `tempo_owner` (never create_all).
* Data is seeded and truncated as the owner (RLS is not FORCEd on owners, so
  fixtures can insert across tenants); the app under test connects as
  `tempo_app`, which is subject to RLS and owns nothing.
* `context_header()` keeps its old signature but now creates a real user,
  membership, role/grant rows and a Tempo-issued session, returning a Bearer
  header — the server derives identity from those rows, never from the header.
"""
from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("TEMPO_ENV", "test")
os.environ.setdefault("TEMPO_SESSION_SIGNING_KEY", "test-only-session-key-not-a-secret-0123456789abcdef")
os.environ.setdefault("TEMPO_ACTION_TOKEN_SECRET", "test-only-action-key-not-a-secret-0123456789abcdef")
os.environ.setdefault("TEMPO_DEV_IDP_ENABLED", "true")

from app import db as db_module  # noqa: E402
from app.core import auth  # noqa: E402
from app.main import app  # noqa: E402
from app.models.identity import (  # noqa: E402
    TempoUser, Tenant, TenantMembership, UserCustomerGrant, UserProviderGrant, UserRoleAssignment, UserSiteGrant,
)


def _url(role: str) -> str:
    pw = os.environ["TEMPO_DB_OWNER_PASSWORD" if role == "tempo_owner" else "TEMPO_DB_APP_PASSWORD"]
    host = os.environ.get("TEMPO_TEST_DB_HOST", "localhost:5439")
    return f"postgresql+psycopg://{role}:{pw}@{host}/tempo_test"


@pytest.fixture(scope="session")
def owner_engine():
    eng = create_engine(_url("tempo_owner"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.set_main_option("sqlalchemy.url", _url("tempo_owner"))
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION tempo_owner"))
        c.execute(text("GRANT USAGE ON SCHEMA public TO tempo_app"))
        c.execute(text("ALTER DEFAULT PRIVILEGES FOR ROLE tempo_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tempo_app"))
        c.execute(text("ALTER DEFAULT PRIVILEGES FOR ROLE tempo_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO tempo_app"))
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def app_engine(owner_engine):
    eng = create_engine(_url("tempo_app"), pool_size=5)
    yield eng
    eng.dispose()


class _FkOrderedSession(Session):
    """Fixture sessions: flush parent tables before children (PostgreSQL enforces FKs; the
    ORM only orders inserts by relationship(), and these models declare none)."""

    def flush(self, objects=None):
        if objects is None and self.new:
            from app.db import Base
            order = {t.name: i for i, t in enumerate(Base.metadata.sorted_tables)}
            for g in sorted({order[o.__table__.name] for o in self.new})[:-1]:
                super().flush([o for o in list(self.new) if order[o.__table__.name] == g])
        super().flush(objects)


class _MaterialisingClient(TestClient):
    """Turns `context_header()` markers into real Bearer tokens backed by DB rows.

    The marker header is *only* a test convenience; the server never reads it (see
    tests/test_forged_identity.py, which proves forged identity headers are ignored).
    """

    _cache: dict

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        marker = headers.pop("X-Test-Principal", None)
        if marker:
            import json
            ctx = json.loads(marker)
            key = marker
            if not hasattr(self, "_tok"):
                self._tok = {}
            if key not in self._tok:
                if ctx["provider_id"]:
                    _ensure_provider(self.session_local, ctx["tenant_id"], ctx["provider_id"])
                self._tok[key] = make_principal(
                    self.session_local, tenant_id=ctx["tenant_id"],
                    user_id=f'{ctx["user_id"]}_{__import__("hashlib").sha1(marker.encode()).hexdigest()[:6]}', roles=tuple(ctx["roles"]),
                    site_ids=tuple(ctx["site_ids"]), customer_ids=tuple(ctx["customer_ids"]), provider_id=ctx["provider_id"])
            headers["Authorization"] = f"Bearer {self._tok[key]}"
            headers["X-Tempo-Tenant"] = ctx["tenant_id"]
            kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


def _ensure_provider(session_local, tenant_id, provider_id):
    from app.models.canonical import LabourProvider
    with session_local() as s:
        if s.get(LabourProvider, provider_id) is None:
            s.add(LabourProvider(provider_id=provider_id, tenant_id=tenant_id, name=provider_id))
            s.commit()


@pytest.fixture()
def client(owner_engine, app_engine, monkeypatch):
    with owner_engine.begin() as c:
        tables = [r[0] for r in c.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))]
        c.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE"))
    app_session = sessionmaker(bind=app_engine, autoflush=False, autocommit=False)
    owner_session = sessionmaker(bind=owner_engine, class_=_FkOrderedSession, autoflush=False, autocommit=False)
    monkeypatch.setattr(db_module, "engine", app_engine)
    monkeypatch.setattr(db_module, "SessionLocal", app_session)
    import app.dependencies as dependencies_module
    monkeypatch.setattr(dependencies_module, "SessionLocal", app_session)
    with _MaterialisingClient(app) as test_client:
        # Fixtures seed as the owner (cross-tenant); the API runs as tempo_app under RLS.
        test_client.session_local = owner_session
        test_client.app_session_local = app_session
        yield test_client


_ROLE_DEFAULT_MFA = True


def make_principal(session_local, *, tenant_id="ten_test", user_id=None, roles=("operations_manager",),
                   site_ids=("site_mel_01",), customer_ids=("cust_A",), provider_id=None, mfa=True) -> str:
    """Create user + membership + roles + grants (as owner) and a live session; returns Bearer token."""
    user_id = user_id or f"usr_{uuid.uuid4().hex[:10]}"
    with session_local() as s:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(tenant_id=tenant_id, name=tenant_id))
            s.flush()
        if s.get(TempoUser, user_id) is None:
            s.add(TempoUser(user_id=user_id, external_subject=f"sub_{user_id}", email=f"{user_id}@example.test"))
            s.flush()
        if s.get(TenantMembership, (user_id, tenant_id)) is None:
            s.add(TenantMembership(user_id=user_id, tenant_id=tenant_id, is_default=True))
        for r in roles:
            s.add(UserRoleAssignment(user_id=user_id, tenant_id=tenant_id, role=r))
        for x in site_ids:
            s.add(UserSiteGrant(user_id=user_id, tenant_id=tenant_id, site_id=x))
        for x in customer_ids:
            s.add(UserCustomerGrant(user_id=user_id, tenant_id=tenant_id, customer_id=x))
        if provider_id:
            s.add(UserProviderGrant(user_id=user_id, tenant_id=tenant_id, provider_id=provider_id))
        s.flush()
        user = s.get(TempoUser, user_id)
        issued = auth.create_session(s, user, mfa=mfa, auth_method="test")
        s.commit()
    return issued.access_token


def context_header(**overrides) -> dict[str, str]:
    """Backwards-compatible helper: stashes the requested principal shape; `client.as_` resolves it.

    Returns a lazily-materialised marker header that the `client` wrapper turns into a real
    Bearer token. See `_TokenMaterialiser` below.
    """
    ctx = {"tenant_id": "ten_test", "site_ids": ["site_mel_01"], "customer_ids": ["cust_A"],
           "user_id": "usr_test", "roles": ["operations_manager"], "provider_id": None}
    ctx.update({k: v for k, v in overrides.items() if k in ctx})
    import json
    return {"X-Test-Principal": json.dumps(ctx)}


def enrol_kiosk(client, *, tenant_id="ten_test", site_ids=("site_mel_01",), name="Dock kiosk") -> dict[str, str]:
    """Create + enrol a device through the real redeem path; returns its Bearer header."""
    from app.core import kiosk
    from app.models.identity import KioskDevice

    with client.session_local() as s:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(tenant_id=tenant_id, name=tenant_id))
            s.flush()
        d = KioskDevice(tenant_id=tenant_id, site_ids=list(site_ids), name=name)
        s.add(d)
        s.flush()
        code = kiosk.new_enrolment_code(d)
        s.commit()
    r = client.post("/v1/kiosk/enrol", json={"enrolment_code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['device_credential']}"}
