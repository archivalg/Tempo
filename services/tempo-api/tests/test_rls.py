"""Gate 1 evidence: PostgreSQL RLS with the real non-owner runtime role (ADR-0011)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app import db as db_module
from app.models.canonical import LabourProvider, Worker


def _seed(owner):
    with owner() as s:
        for t in ("ten_a", "ten_b"):
            s.add(LabourProvider(provider_id=f"prov_{t}", tenant_id=t, name=t))
        s.flush()
        s.add(Worker(worker_id="wa", tenant_id="ten_a", employment_type="permanent", home_site="s", status="active"))
        s.add(Worker(worker_id="wb", tenant_id="ten_b", employment_type="permanent", home_site="s", status="active"))
        s.commit()


def test_runtime_role_is_not_owner_and_cannot_bypass_rls(client, app_engine):
    with app_engine.connect() as c:
        r = c.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert (r.rolsuper, r.rolbypassrls) == (False, False)
        owned = c.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tableowner = current_user")).scalar()
        assert owned == 0
        with pytest.raises(ProgrammingError):
            c.execute(text("ALTER TABLE worker DISABLE ROW LEVEL SECURITY"))


def test_every_tenant_table_has_rls_and_a_policy(owner_engine):
    with owner_engine.connect() as c:
        tables = [r[0] for r in c.execute(text(
            "SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='tenant_id'"))]
        assert tables
        for t in tables:
            rls = c.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname=:t"), {"t": t}).scalar()
            pol = c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename=:t"), {"t": t}).scalar()
            assert rls and pol >= 1, f"{t}: RLS missing (add it in a migration)"


def test_no_context_returns_nothing_and_cannot_write(client, app_engine):
    _seed(client.session_local)
    with app_engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM worker")).scalar() == 0  # under-filtered SQL, no context
        with pytest.raises(DBAPIError):
            c.execute(text("INSERT INTO labour_provider(provider_id, tenant_id, name) VALUES ('p','ten_a','x')"))


def test_under_filtered_query_sees_only_own_tenant(client):
    _seed(client.session_local)
    with db_module.tenant_session("ten_a") as s:
        rows = s.execute(text("SELECT worker_id FROM worker")).scalars().all()  # deliberately no WHERE
        assert rows == ["wa"]
        joined = s.execute(text("SELECT w.worker_id FROM worker w CROSS JOIN labour_provider p")).scalars().all()
        assert set(joined) == {"wa"}  # cross-tenant join cannot reach ten_b rows


def test_cross_tenant_write_is_rejected_and_update_delete_touch_nothing(client):
    _seed(client.session_local)
    with db_module.tenant_session("ten_a") as s:
        with pytest.raises(DBAPIError):
            s.execute(text("INSERT INTO labour_provider(provider_id, tenant_id, name) VALUES ('x','ten_b','evil')"))
    with db_module.tenant_session("ten_a") as s:
        assert s.execute(text("UPDATE worker SET status='gone' WHERE worker_id='wb'")).rowcount == 0
        assert s.execute(text("DELETE FROM worker WHERE worker_id='wb'")).rowcount == 0


def test_moving_a_row_to_another_tenant_is_rejected(client):
    _seed(client.session_local)
    with db_module.tenant_session("ten_a") as s:
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE worker SET tenant_id='ten_b' WHERE worker_id='wa'"))


def test_pooled_connection_reuse_does_not_leak_tenant_context(client, app_engine):
    _seed(client.session_local)
    for _ in range(5):
        with db_module.tenant_session("ten_a") as s:
            assert s.execute(text("SELECT count(*) FROM worker")).scalar() == 1
        with app_engine.connect() as c:  # same pool, next borrower: no context must survive
            assert c.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in (None, "")
            assert c.execute(text("SELECT count(*) FROM worker")).scalar() == 0


def test_tenant_switching_within_one_pool_isolates(client):
    _seed(client.session_local)
    seen = []
    for t in ("ten_a", "ten_b", "ten_a", "ten_b"):
        with db_module.tenant_session(t) as s:
            seen.append(s.execute(text("SELECT worker_id FROM worker")).scalar_one())
    assert seen == ["wa", "wb", "wa", "wb"]


def test_audit_tables_are_append_only_for_runtime_role(client, app_engine):
    with client.session_local() as s:
        s.execute(text("INSERT INTO security_audit_event(event_id,actor_type,actor_id,tenant_id,action,decision,correlation_id,created_at) "
                       "VALUES ('e1','user','u','ten_a','x','allowed','c',now())"))
        s.commit()
    with db_module.tenant_session("ten_a") as s:
        assert s.execute(text("SELECT count(*) FROM security_audit_event")).scalar() == 1
        with pytest.raises(ProgrammingError):
            s.execute(text("DELETE FROM security_audit_event"))
    with db_module.tenant_session("ten_a") as s:
        with pytest.raises(ProgrammingError):
            s.execute(text("UPDATE security_audit_event SET decision='denied'"))


def test_identity_tables_invisible_without_auth_phase(client, app_engine):
    with client.session_local() as s:
        s.execute(text("INSERT INTO tempo_user(user_id, external_subject, account_status, token_version, created_at, updated_at) "
                       "VALUES ('u1','sub1','active',0,now(),now())"))
        s.commit()
    with app_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM tempo_user")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM user_session")).scalar() == 0
