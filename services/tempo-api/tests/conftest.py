from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import db as db_module
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    test_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", test_session_local)

    import app.dependencies as dependencies_module

    monkeypatch.setattr(dependencies_module, "SessionLocal", test_session_local)

    db_module.init_db()

    with TestClient(app) as test_client:
        yield test_client


def context_header(**overrides) -> dict[str, str]:
    context = {
        "tenant_id": "ten_test",
        "company_id": "cmp_test",
        "site_ids": ["site_mel_01"],
        "customer_ids": ["cust_A"],
        "user_id": "usr_test",
        "roles": ["operations_manager"],
        "purpose": "labour.plan",
        "correlation_id": "cor_test_1",
    }
    context.update(overrides)
    return {"X-Tempo-Context": json.dumps(context)}
