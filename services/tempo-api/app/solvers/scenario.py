"""Robust and Scenario Optimisation (Monte Carlo) — AI Labour Optimisation
Spec §3.10 / Appendix A.10.

Stress-tests a workforce_mix plan under demand volatility, absenteeism and
productivity drift, reporting a cost distribution, SLA-breach probability
and labour-risk range rather than a single point estimate.

Scope reduction — the biggest one in this module: the formal model's
second stage (§A.10) is itself an optimisation ("Q(x,ω) = min RecourseCost
(...)") to be solved per scenario. Re-solving a MILP per Monte Carlo draw
(the policy default is 200 scenarios) is not tractable synchronously, and
this codebase has no async run worker yet (§18's "heavy scenario runs
return async with progress state" isn't built — tracked in docs/roadmap.md
as Phase D/F scope). Instead, recourse per scenario is computed
analytically, in the same cost order a MILP minimising recourse cost would
pick (cheapest lever first): overtime, then temporary (labour-hire)
capacity up to a surge cap, then unmet demand penalised at
sla_penalty_per_hour. This approximates what a per-scenario MILP would
choose without the runtime cost of actually solving one.

Objective posture: request.configuration.objective_profile == "lowest_risk"
selects the robust (worst-case) form from §A.10; every other profile uses
the stochastic (expected-value) form — reusing the existing enum instead
of adding a scenario-specific request field.

Scenario draws use a seeded RNG (policy's scenario_random_seed) so a run is
reproducible from its inputs and policy version alone, consistent with the
Integration Spec's run-immutability requirement — not genuine randomness.
"""
from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.core.policy import resolve_policy
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome
from app.solvers.labour_requirement import translate_labour_requirement
from app.solvers.workforce_mix import solve_workforce_mix

TEMP_LABOUR_SURGE_CAP_RATIO = 1.0  # temp labour can at most match existing baseline capacity


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def solve_scenario(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    policy = resolve_policy(db, tenant_id, request.configuration.policy_version)
    c = policy.constraints
    hours_per_worker_per_day = c["hours_per_worker_per_day"]
    max_overtime_ratio_hours = c["max_overtime_hours_per_worker_per_day"]
    default_rate = c["default_rate"]
    default_overtime_multiplier = c["default_overtime_multiplier"]
    default_hire_surcharge = c["default_hire_surcharge"]
    sla_penalty_per_hour = c["sla_penalty_per_hour"]
    scenario_count = int(c["scenario_count"])
    seed = c["scenario_random_seed"]
    demand_cv = c["scenario_demand_volatility_cv"]
    absenteeism_mean = c["scenario_absenteeism_rate_mean"]
    absenteeism_std = c["scenario_absenteeism_rate_std"]
    productivity_std = c["scenario_productivity_drift_std"]

    mix = solve_workforce_mix(db, tenant_id, site_ids, request)
    assignments = mix.result["assignments"]
    if not assignments:
        raise InsufficientData("workforce mix produced no first-stage plan to stress-test")

    labour_req = translate_labour_requirement(db, tenant_id, site_ids, request)
    total_required_hours = sum(row["hours"] for row in labour_req.result["hours_requirement"])
    if total_required_hours <= 0:
        raise InsufficientData("labour requirement translation produced no hours to stress-test")

    total_headcount = sum(row["headcount"] for row in assignments)
    total_capacity_hours = total_headcount * hours_per_worker_per_day
    first_stage_cost = float(mix.result["kpis"]["labour_cost"]["amount"])
    hire_rate = default_rate + default_hire_surcharge
    temp_labour_cap_hours = total_capacity_hours * TEMP_LABOUR_SURGE_CAP_RATIO
    overtime_capacity_hours = total_headcount * max_overtime_ratio_hours

    rng = random.Random(seed)
    total_costs: list[float] = []
    unmet_hours_by_scenario: list[float] = []

    for _ in range(scenario_count):
        demand_multiplier = _clip(rng.gauss(1.0, demand_cv), 0.1, 3.0)
        absenteeism_rate = _clip(rng.gauss(absenteeism_mean, absenteeism_std), 0.0, 0.9)
        productivity_multiplier = _clip(rng.gauss(1.0, productivity_std), 0.3, 2.0)

        available_capacity = total_capacity_hours * (1 - absenteeism_rate)
        required_hours = total_required_hours * demand_multiplier / productivity_multiplier
        gap = required_hours - available_capacity

        if gap <= 0:
            unmet_hours_by_scenario.append(0.0)
            total_costs.append(first_stage_cost)
            continue

        overtime_used = min(gap, overtime_capacity_hours)
        remaining = gap - overtime_used
        temp_used = min(remaining, temp_labour_cap_hours)
        unmet_hours = max(0.0, remaining - temp_used)

        recourse_cost = (
            overtime_used * default_rate * default_overtime_multiplier
            + temp_used * hire_rate
            + unmet_hours * sla_penalty_per_hour
        )
        unmet_hours_by_scenario.append(unmet_hours)
        total_costs.append(first_stage_cost + recourse_cost)

    total_costs.sort()
    n = len(total_costs)
    mean_cost = sum(total_costs) / n
    p50 = total_costs[n // 2]
    p90 = total_costs[min(n - 1, int(n * 0.9))]
    worst_case_cost = total_costs[-1]
    breach_count = sum(1 for h in unmet_hours_by_scenario if h > 0)
    breach_probability = round(breach_count / n, 4)

    robust_mode = request.configuration.objective_profile == "lowest_risk"
    planning_cost = worst_case_cost if robust_mode else mean_cost

    return SolverOutcome(
        result={
            "mode": "robust_worst_case" if robust_mode else "stochastic_expected_value",
            "scenario_count": n,
            "kpis": {
                "planning_cost": {"amount": f"{planning_cost:.2f}", "currency": "AUD"},
                "cost_distribution": {
                    "mean": {"amount": f"{mean_cost:.2f}", "currency": "AUD"},
                    "p50": {"amount": f"{p50:.2f}", "currency": "AUD"},
                    "p90": {"amount": f"{p90:.2f}", "currency": "AUD"},
                    "min": {"amount": f"{total_costs[0]:.2f}", "currency": "AUD"},
                    "max": {"amount": f"{worst_case_cost:.2f}", "currency": "AUD"},
                },
                "sla_breach_probability": breach_probability,
                "labour_risk_hours": {"min": round(min(unmet_hours_by_scenario), 2), "max": round(max(unmet_hours_by_scenario), 2)},
            },
        },
        baseline={"method": "single_point_forecast", "cost": {"amount": f"{first_stage_cost:.2f}", "currency": "AUD"}},
        proposed={"method": "monte_carlo_scenario_planning", "cost": {"amount": f"{planning_cost:.2f}", "currency": "AUD"}},
        delta={"cost": {"amount": f"{planning_cost - first_stage_cost:.2f}", "currency": "AUD"}},
        dollar_value=None,
        confidence_components=ConfidenceComponents(
            completeness=mix.confidence_components.completeness,
            freshness=mix.confidence_components.freshness,
            mapping_quality=mix.confidence_components.mapping_quality,
            forecast_validation=mix.confidence_components.forecast_validation,
            constraint_coverage=1.0 if breach_probability == 0 else 0.6,
            solution_quality=0.8,  # analytic recourse approximation, not a re-solved MILP per scenario
        ),
        primary_drivers=[
            f"Monte Carlo over {n} scenarios ({'robust worst-case' if robust_mode else 'stochastic expected-value'} posture)",
        ]
        + ([f"SLA breach in {breach_count} of {n} scenarios ({round(100*breach_probability,1)}%)"] if breach_count else []),
        missing_evidence=mix.missing_evidence,
        assumptions=mix.assumptions
        + [
            f"policy '{policy.policy_version}': demand volatility CV {demand_cv}, absenteeism ~N({absenteeism_mean},{absenteeism_std}), "
            f"productivity drift std {productivity_std}, {scenario_count} scenarios, seed {seed}",
            "recourse computed analytically (overtime, then temp labour up to a surge cap, then unmet demand), "
            "not by re-solving a MILP per scenario",
        ],
        feasibility="feasible_with_slack" if breach_count else "feasible",
    )
