"""Order-driven-planning Stage 0 finding: a genuinely infeasible solver run must persist as a
terminal, auditable "failed" run (not roll back and vanish like InsufficientData does). See
docs/order-driven-planning.md.
"""
from __future__ import annotations

import uuid

import app.api.v1.runs as runs_module
from app.solvers.base import SolverInfeasible

from .conftest import context_header
from .test_run_endpoint import VALID_REQUEST, _seed


def _headers():
    headers = context_header()
    headers["Idempotency-Key"] = str(uuid.uuid4())
    return headers


def test_solver_infeasible_persists_a_failed_run_instead_of_vanishing(client, monkeypatch):
    _seed(client)

    def _boom(db, tenant_id, site_ids, request):
        raise SolverInfeasible("named roster CP-SAT model returned infeasible — hard constraints cannot all be satisfied for this scope and window")

    monkeypatch.setitem(runs_module._SOLVERS, "named_roster", _boom)
    response = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "failed"
    assert "infeasible" in body["warnings"][0]
    run_id = body["run_id"]

    fetched = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()
    assert fetched["status"] == "failed"
    assert fetched["explanation"]["feasibility"] == "infeasible"
    assert "infeasible" in fetched["explanation"]["primary_drivers"][0]
    assert fetched["result"] is None  # no plan was produced — never shown as if one was

    listed = client.get("/v1/runs", params={"status": "failed"}, headers=context_header()).json()
    assert run_id in {r["run_id"] for r in listed["runs"]}  # a failed run is a real, listable, auditable event
