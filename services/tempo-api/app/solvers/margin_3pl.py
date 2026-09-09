"""3PL Cost-to-Serve and Margin Optimisation (MILP) — AI Labour Optimisation
Spec §3.9 / Appendix A.9.

Optimises labour deployment against contractual sell rates so labour
decisions can be evaluated on contribution margin, not only cost — the
customer-profitability counterpart to workforce_mix's pure cost view.

Restricted per Integration Spec §5.2 (labour.margin.read: "Finance, 3PL
Commercial ... View customer cost-to-serve and margin outputs") — enforced
in app/api/v1/runs.py, not here; this module only computes the numbers.

Scope reductions:
- Demand is read directly from DemandBucket for the planning window itself
  (customer_id populated), not forecast — customer-split contracted volumes
  are typically known in advance, unlike the aggregate operational demand
  demand_forecast predicts, and Phase A's forecast_demand doesn't carry
  customer_id through anyway (it aggregates by activity only).
- Labour cost uses one representative LabourCostRule per role (preferring
  'permanent', else any configured type, else default_rate) rather than
  re-deciding the internal/labour-hire mix — that trade-off is
  workforce_mix's job; this model focuses on the service/profitability
  trade-off (how much of each customer's demand to serve) given a single
  blended labour rate.
- SLA minimum service floors (q >= SLAmin) aren't modelled — no canonical
  entity carries a per-contract minimum service percentage yet; only the
  missed-service penalty (sla_penalty, defaulting to
  margin_default_sla_penalty_per_unit) discourages leaving demand unserved.
- Overhead is a flat policy rate per labour-hour (margin_overhead_rate_per_hour),
  not the real allocation methodology a finance system would apply.
"""
from __future__ import annotations

from collections import defaultdict

from ortools.linear_solver import pywraplp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.policy import resolve_policy
from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SellRateContract, WorkStandard
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome

DEFAULT_TIME_PER_UNIT_SECONDS = 60.0
PREFERRED_LABOUR_TYPE = "permanent"


def _day_bucket(dt) -> str:
    return dt.date().isoformat()


def _work_standard_lookup(db: Session, tenant_id: str) -> dict[str, float]:
    rows = db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == tenant_id)).all()
    by_activity: dict[str, WorkStandard] = {}
    for row in rows:
        current = by_activity.get(row.activity)
        if current is None or row.effective_from > current.effective_from:
            by_activity[row.activity] = row
    return {activity: row.time_per_unit_seconds for activity, row in by_activity.items()}


def _role_zone_map(db: Session, tenant_id: str, site_id: str) -> dict[str, list[tuple[str, str, float]]]:
    rows = db.scalars(
        select(ActivityRoleZoneMap)
        .where(ActivityRoleZoneMap.tenant_id == tenant_id)
        .where(ActivityRoleZoneMap.site_id == site_id)
    ).all()
    mapping: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for row in rows:
        mapping[row.activity].append((row.role, row.zone, row.weight))
    return mapping


def _sell_rate_lookup(db: Session, tenant_id: str) -> list[SellRateContract]:
    return db.scalars(select(SellRateContract).where(SellRateContract.tenant_id == tenant_id)).all()


def _contract_for(contracts: list[SellRateContract], customer_id: str, activity: str, day) -> SellRateContract | None:
    for row in contracts:
        if row.customer_id != customer_id or row.activity != activity:
            continue
        if row.effective_from.date() > day:
            continue
        if row.effective_to is not None and row.effective_to.date() < day:
            continue
        return row
    return None


def _rate_lookup(db: Session, tenant_id: str) -> dict[str, LabourCostRule]:
    """One representative LabourCostRule per role, preferring 'permanent'."""
    rows = db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == tenant_id)).all()
    by_role: dict[str, LabourCostRule] = {}
    for row in rows:
        current = by_role.get(row.role)
        if current is None or (row.labour_type == PREFERRED_LABOUR_TYPE and current.labour_type != PREFERRED_LABOUR_TYPE):
            by_role[row.role] = row
    return by_role


def solve_margin_3pl(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    policy = resolve_policy(db, tenant_id, request.configuration.policy_version)
    c = policy.constraints
    hours_per_worker_per_day = c["hours_per_worker_per_day"]
    max_overtime = c["max_overtime_hours_per_worker_per_day"]
    default_rate = c["default_rate"]
    default_overtime_multiplier = c["default_overtime_multiplier"]
    default_sell_rate = c["margin_default_sell_rate"]
    default_sla_penalty = c["margin_default_sla_penalty_per_unit"]
    overhead_rate_per_hour = c["margin_overhead_rate_per_hour"]

    window = request.planning_window
    demand_rows = db.scalars(
        select(DemandBucket)
        .where(DemandBucket.tenant_id == tenant_id)
        .where(DemandBucket.site_id == site_id)
        .where(DemandBucket.customer_id.is_not(None))
        .where(DemandBucket.interval_start >= window.start)
        .where(DemandBucket.interval_start < window.end)
    ).all()
    if not demand_rows:
        raise InsufficientData(f"no customer-attributed demand_bucket rows for site '{site_id}' within the planning window")

    volume_by_bucket: dict[tuple, float] = defaultdict(float)
    for row in demand_rows:
        volume_by_bucket[(row.customer_id, row.activity, _day_bucket(row.interval_start))] += row.volume

    time_per_unit = _work_standard_lookup(db, tenant_id)
    role_zone_map = _role_zone_map(db, tenant_id, site_id)
    contracts = _sell_rate_lookup(db, tenant_id)
    rate_rules = _rate_lookup(db, tenant_id)

    activities = {activity for _, activity, _ in volume_by_bucket}
    activities_with_mapping = activities & role_zone_map.keys()
    customer_activity_pairs = {(cust, act) for cust, act, _ in volume_by_bucket}
    pairs_with_contract = {
        (cust, act) for cust, act in customer_activity_pairs if _contract_for(contracts, cust, act, window.start.date())
    }

    solver = pywraplp.Solver.CreateSolver("CBC")
    q: dict[tuple, object] = {}
    u: dict[tuple, object] = {}
    x: dict[tuple[str, str, str], object] = {}
    o: dict[tuple[str, str, str], object] = {}
    revenue_terms = []
    penalty_terms = []
    labour_terms = []
    capacity_by_role_zone_day: dict[tuple[str, str, str], list] = defaultdict(list)

    for (customer_id, activity, day), volume in volume_by_bucket.items():
        contract = _contract_for(contracts, customer_id, activity, window.start.date())
        rate = float(contract.rate) if contract else default_sell_rate
        sla_penalty = float(contract.sla_penalty) if contract and contract.sla_penalty else default_sla_penalty

        q[(customer_id, activity, day)] = solver.NumVar(0, volume, f"q_{customer_id}_{activity}_{day}")
        u[(customer_id, activity, day)] = solver.NumVar(0, volume, f"u_{customer_id}_{activity}_{day}")
        solver.Add(q[(customer_id, activity, day)] + u[(customer_id, activity, day)] == volume)
        revenue_terms.append((q[(customer_id, activity, day)], rate))
        penalty_terms.append((u[(customer_id, activity, day)], sla_penalty))

        seconds_per_unit = time_per_unit.get(activity, DEFAULT_TIME_PER_UNIT_SECONDS)
        targets = role_zone_map.get(activity) or [("general", "general", 1.0)]
        weight_total = sum(w for _, _, w in targets) or 1.0
        for role, zone, weight in targets:
            share = weight / weight_total
            capacity_by_role_zone_day[(role, zone, day)].append((q[(customer_id, activity, day)], share * seconds_per_unit / 3600))

    for (role, zone, day), terms in capacity_by_role_zone_day.items():
        xi = solver.IntVar(0, solver.infinity(), f"x_{role}_{zone}_{day}")
        oi = solver.NumVar(0, solver.infinity(), f"o_{role}_{zone}_{day}")
        x[(role, zone, day)] = xi
        o[(role, zone, day)] = oi
        solver.Add(oi <= max_overtime * xi)
        solver.Add(sum(coeff * var for var, coeff in terms) <= hours_per_worker_per_day * xi + oi)

        rule = rate_rules.get(role)
        rate = float(rule.rate) if rule else default_rate
        ot_multiplier = float(rule.overtime_multiplier) if rule and rule.overtime_multiplier else default_overtime_multiplier
        labour_terms.append((xi, rate * hours_per_worker_per_day + overhead_rate_per_hour * hours_per_worker_per_day))
        labour_terms.append((oi, rate * ot_multiplier + overhead_rate_per_hour))

    solver.Maximize(
        sum(coeff * var for var, coeff in revenue_terms)
        - sum(coeff * var for var, coeff in penalty_terms)
        - sum(coeff * var for var, coeff in labour_terms)
    )
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise InsufficientData("3PL margin MILP did not return a usable solution")

    total_revenue = sum(coeff * var.solution_value() for var, coeff in revenue_terms)
    total_penalty = sum(coeff * var.solution_value() for var, coeff in penalty_terms)
    total_labour_cost = sum(coeff * var.solution_value() for var, coeff in labour_terms)
    contribution_margin = total_revenue - total_penalty - total_labour_cost
    total_volume = sum(volume_by_bucket.values())
    total_served = sum(var.solution_value() for var in q.values())
    service_pct = round(100 * total_served / total_volume, 2) if total_volume else 100.0

    by_customer: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "served": 0.0, "unserved": 0.0})
    for (customer_id, activity, day), var in q.items():
        by_customer[customer_id]["served"] += var.solution_value()
    for (customer_id, activity, day), var in u.items():
        by_customer[customer_id]["unserved"] += var.solution_value()

    baseline_margin = total_revenue - total_labour_cost  # "serve everything, ignore SLA penalty trade-off" baseline

    return SolverOutcome(
        result={
            "by_customer": [
                {"customer_id": cust, "served_units": round(v["served"], 2), "unserved_units": round(v["unserved"], 2)}
                for cust, v in sorted(by_customer.items())
            ],
            "kpis": {
                "contribution_margin": {"amount": f"{contribution_margin:.2f}", "currency": "AUD"},
                "revenue": {"amount": f"{total_revenue:.2f}", "currency": "AUD"},
                "labour_cost": {"amount": f"{total_labour_cost:.2f}", "currency": "AUD"},
                "service_pct": service_pct,
            },
        },
        baseline={"method": "serve_all_ignore_penalty", "contribution_margin": {"amount": f"{baseline_margin:.2f}", "currency": "AUD"}},
        proposed={"method": "milp_margin_optimised", "contribution_margin": {"amount": f"{contribution_margin:.2f}", "currency": "AUD"}},
        delta={"contribution_margin": {"amount": f"{contribution_margin - baseline_margin:.2f}", "currency": "AUD"}},
        dollar_value={"amount": f"{contribution_margin - baseline_margin:.2f}", "currency": "AUD"},
        confidence_components=ConfidenceComponents(
            completeness=round(len(pairs_with_contract) / len(customer_activity_pairs), 4) if customer_activity_pairs else 0.0,
            freshness=1.0,
            mapping_quality=round(len(activities_with_mapping) / len(activities), 4) if activities else 0.0,
            forecast_validation=1.0,
            constraint_coverage=1.0 if total_served == total_volume else 0.6,
            solution_quality=1.0 if status == pywraplp.Solver.OPTIMAL else 0.7,
        ),
        primary_drivers=[
            f"MILP over {len(customer_activity_pairs)} customer/activity pairs across {len(capacity_by_role_zone_day)} role/zone/day capacity buckets",
        ]
        + ([f"{round(total_volume - total_served, 1)} units left unserved — capacity or SLA penalty trade-off"] if total_served < total_volume else []),
        missing_evidence=(
            [f"{len(customer_activity_pairs) - len(pairs_with_contract)} of {len(customer_activity_pairs)} customer/activity pairs have no SellRateContract; used default sell rate ${default_sell_rate}/unit"]
            if len(pairs_with_contract) < len(customer_activity_pairs)
            else []
        )
        + (
            [f"{len(activities) - len(activities_with_mapping)} of {len(activities)} activities have no ActivityRoleZoneMap; assigned to a single 'general/general' bucket"]
            if activities - activities_with_mapping
            else []
        ),
        assumptions=[
            "customer-split demand read directly from demand_bucket for the planning window (assumed known/contracted), not forecast",
            f"policy '{policy.policy_version}': overhead ${overhead_rate_per_hour}/labour-hour, "
            f"default sell rate ${default_sell_rate}/unit, default SLA penalty ${default_sla_penalty}/unit",
            "labour cost uses one representative rate per role (preferring 'permanent'), not a re-optimised internal/hire mix",
        ],
        feasibility="feasible_with_slack" if total_served < total_volume else "feasible",
    )
