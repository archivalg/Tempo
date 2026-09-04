"""GET /v1/data-readiness — §7.3."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_request_context
from app.models import canonical
from app.schemas.readiness import CAPABILITY_REQUIRED_DOMAINS, DataReadinessResponse, DomainReadiness
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["readiness"])

_DOMAIN_MODELS = {
    "worker": canonical.Worker,
    "skill_certification": canonical.SkillCertification,
    "availability": canonical.Availability,
    "demand_bucket": canonical.DemandBucket,
    "work_standard": canonical.WorkStandard,
    "labour_cost_rule": canonical.LabourCostRule,
}


def _domain_readiness(db: Session, tenant_id: str, domain: str) -> DomainReadiness:
    model = _DOMAIN_MODELS.get(domain)
    if model is None:
        return DomainReadiness(domain=domain, status="not_ready", warning="domain has no canonical mapping yet")
    existing = db.scalar(select(model).where(model.tenant_id == tenant_id).limit(1))
    if existing is None:
        return DomainReadiness(domain=domain, status="not_ready", warning=f"no {domain} records ingested for tenant")
    return DomainReadiness(domain=domain, status="ready", freshness_seconds=0)


@router.get("/data-readiness", response_model=DataReadinessResponse)
def get_data_readiness(
    capability: str = Query(...),
    site_id: str | None = Query(default=None),
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> DataReadinessResponse:
    required_domains = CAPABILITY_REQUIRED_DOMAINS.get(capability, [])
    domain_results = [_domain_readiness(db, context.tenant_id, domain) for domain in required_domains]

    blocking_issues: list[str] = []
    warnings: list[str] = []
    for result in domain_results:
        if result.status == "not_ready":
            warnings.append(result.warning or f"{result.domain} is not ready")
        elif result.status == "partial" and result.warning:
            warnings.append(result.warning)

    ready_count = sum(1 for r in domain_results if r.status == "ready")
    score = round(ready_count / len(domain_results), 4) if domain_results else 0.0

    if not domain_results:
        status = "not_ready"
        blocking_issues.append(f"unknown capability '{capability}'")
    elif score == 1.0:
        status = "ready"
    elif score >= 0.5:
        status = "ready_with_warnings"
    else:
        status = "not_ready"
        blocking_issues.extend(warnings)

    return DataReadinessResponse(
        status=status,
        score=score,
        as_of=datetime.now(timezone.utc),
        required_domains=domain_results,
        blocking_issues=blocking_issues,
        warnings=warnings,
    )
