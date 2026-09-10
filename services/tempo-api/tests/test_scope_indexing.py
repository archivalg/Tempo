"""DAT-05: OptimisationRun/ActionRequest's site and customer scope is now
also stored as real, indexed rows/columns (app/models/runs.py's
OptimisationRunSite/OptimisationRunCustomer, ActionRequest.site_id) —
not just inside the immutable request/target JSON. These tests prove the
derived rows are actually populated, not just declared.
"""
from __future__ import annotations

from app.models.runs import ActionRequest, OptimisationRunCustomer, OptimisationRunSite

from .conftest import context_header
from .test_run_endpoint import VALID_REQUEST, _headers, _seed


def test_run_creation_populates_indexed_site_and_customer_rows(client):
    _seed(client)
    run_id = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers()).json()["run_id"]

    with client.session_local() as session:
        sites = session.query(OptimisationRunSite).filter_by(run_id=run_id).all()
        customers = session.query(OptimisationRunCustomer).filter_by(run_id=run_id).all()

    assert [s.site_id for s in sites] == ["site_mel_01"]
    assert [c.customer_id for c in customers] == ["cust_A"]
    assert all(s.tenant_id == "ten_test" for s in sites)


def test_action_request_site_id_column_matches_target(client):
    _seed(client)
    recommendation_id = client.post(
        "/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers()
    ).json()["recommendation_id"]

    action_id = client.post(
        "/v1/actions/validate",
        json={
            "action_type": "publish_roster",
            "recommendation_id": recommendation_id,
            "target": {"system": "deputy", "connection_id": "con_1", "site_id": "site_mel_01"},
        },
        headers=context_header(),
    ).json()["action_id"]

    with client.session_local() as session:
        action = session.get(ActionRequest, action_id)

    assert action.site_id == "site_mel_01"
    assert action.target["site_id"] == "site_mel_01"
