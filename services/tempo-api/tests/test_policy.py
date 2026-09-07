"""Policy resolution — OD-08 generalized to the mix/roster policy constants.
Checks the "versioned code defaults + admin-override slot" pattern: no
configured policy uses DEFAULT_POLICY_VERSION's values; a stored
OptimisationPolicy overrides only the keys it sets, merging over defaults.
"""
from __future__ import annotations

from app.core.policy import DEFAULT_CONSTRAINTS, DEFAULT_POLICY_VERSION, DEFAULT_WEIGHTS, resolve_policy
from app.models.canonical import OptimisationPolicy


def test_no_configured_policy_returns_code_defaults(client):
    with client.session_local() as db:
        resolved = resolve_policy(db, "ten_no_policy")
    assert resolved.policy_version == DEFAULT_POLICY_VERSION
    assert resolved.constraints == DEFAULT_CONSTRAINTS
    assert resolved.weights == DEFAULT_WEIGHTS


def test_stored_policy_partially_overrides_defaults(client):
    with client.session_local() as db:
        db.add(
            OptimisationPolicy(
                policy_version="ten_a-v1",
                tenant_id="ten_a",
                constraints={"internal_min_ratio": 0.8},
                weights={"completeness": 0.5},
                tolerances={},
            )
        )
        db.commit()

        resolved = resolve_policy(db, "ten_a")
    assert resolved.policy_version == "ten_a-v1"
    assert resolved.constraints["internal_min_ratio"] == 0.8
    # Untouched keys still come from the code defaults.
    assert resolved.constraints["hire_max_ratio"] == DEFAULT_CONSTRAINTS["hire_max_ratio"]
    assert resolved.weights["completeness"] == 0.5
    assert resolved.weights["freshness"] == DEFAULT_WEIGHTS["freshness"]


def test_requesting_another_tenants_policy_version_falls_back_to_defaults(client):
    with client.session_local() as db:
        db.add(
            OptimisationPolicy(
                policy_version="ten_b-v1", tenant_id="ten_b", constraints={"internal_min_ratio": 0.9}, weights={}, tolerances={}
            )
        )
        db.commit()

        # ten_a asking for ten_b's policy_version must not get ten_b's constraints.
        resolved = resolve_policy(db, "ten_a", requested_policy_version="ten_b-v1")
    assert resolved.policy_version == DEFAULT_POLICY_VERSION
    assert resolved.constraints["internal_min_ratio"] == DEFAULT_CONSTRAINTS["internal_min_ratio"]


def test_unknown_requested_policy_version_falls_back_to_tenant_latest(client):
    with client.session_local() as db:
        db.add(
            OptimisationPolicy(
                policy_version="ten_c-v1", tenant_id="ten_c", constraints={"hire_max_ratio": 0.1}, weights={}, tolerances={}
            )
        )
        db.commit()

        resolved = resolve_policy(db, "ten_c", requested_policy_version="does-not-exist")
    assert resolved.constraints["hire_max_ratio"] == 0.1
