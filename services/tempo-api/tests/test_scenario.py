"""Robust and Scenario Optimisation — checks the property that makes this
model worth having: the robust (worst-case) posture reports a higher
planning cost than the stochastic (expected-value) posture over the exact
same scenario draws, and results are reproducible from the same policy
version rather than genuinely random on every run (Integration Spec's
run-immutability requirement).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.canonical import OptimisationPolicy
from app.schemas.runs import PlanningWindow, RunConfiguration, RunRequest, RunScope
from app.solvers.scenario import solve_scenario
from .factories import seed_named_roster_scenario

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"


def _request(objective_profile: str = "balanced", policy_version: str | None = None) -> RunRequest:
    return RunRequest(
        request_id="req_test",
        scope=RunScope(tenant_id="ten_test", site_ids=[SITE_ID], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(
            start=WINDOW_START, end=datetime(2026, 9, 15, tzinfo=timezone.utc), timezone="Australia/Melbourne", bucket_minutes=60
        ),
        configuration=RunConfiguration(objective_profile=objective_profile, policy_version=policy_version),
    )


def test_robust_posture_never_costs_less_than_stochastic_over_same_scenarios(client):
    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        stochastic = solve_scenario(db, "ten_test", [SITE_ID], _request("balanced"))
        robust = solve_scenario(db, "ten_test", [SITE_ID], _request("lowest_risk"))

    stochastic_cost = float(stochastic.result["kpis"]["planning_cost"]["amount"])
    robust_cost = float(robust.result["kpis"]["planning_cost"]["amount"])
    assert robust_cost >= stochastic_cost
    # Same seed, same underlying scenario draws — only the aggregation differs.
    assert stochastic.result["kpis"]["cost_distribution"] == robust.result["kpis"]["cost_distribution"]


def test_same_inputs_and_policy_reproduce_identical_results(client):
    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        first = solve_scenario(db, "ten_test", [SITE_ID], _request())
        second = solve_scenario(db, "ten_test", [SITE_ID], _request())

    assert first.result["kpis"] == second.result["kpis"]


def test_high_volatility_policy_produces_sla_breach_risk(client):
    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        # Computed before the override row exists — resolve_policy falls back
        # to the tenant's *latest* policy whenever none is explicitly
        # requested, so this must run before pol_stress is inserted or both
        # calls would resolve to it.
        calm = solve_scenario(db, "ten_test", [SITE_ID], _request())

        db.add(
            OptimisationPolicy(
                policy_version="pol_stress",
                tenant_id="ten_test",
                jurisdiction=None,
                constraints={
                    "scenario_demand_volatility_cv": 0.8,
                    "scenario_absenteeism_rate_mean": 0.4,
                    "scenario_absenteeism_rate_std": 0.1,
                },
                weights={},
                tolerances={},
            )
        )
        db.commit()
        stressed = solve_scenario(db, "ten_test", [SITE_ID], _request(policy_version="pol_stress"))

    assert stressed.result["kpis"]["sla_breach_probability"] >= calm.result["kpis"]["sla_breach_probability"]
    assert stressed.result["kpis"]["cost_distribution"]["max"] != calm.result["kpis"]["cost_distribution"]["max"]
