"""Labour Provider — Business Spec §8's UX role ("manage supplied workers,
certifications, shift assignments") and §5's "Labour Hire Portal" module.

Previously a disclosed gap (see services/tempo-api/README.md's and
services/tempo-console/README.md's "Known simplifications"): neither the
canonical model nor the console's tenant/site-scoped identity had any
concept of "which workers belong to which provider." This module adds
that — a `LabourProvider` registry (app/models/canonical.py), a
`Worker.provider_id` FK, a new `labour_provider` role/`labour.provider.manage`
permission (app/schemas/tenancy.py — neither exists in the Integration
Spec's §5.2 table), and endpoints scoped so a Labour Provider caller can
only ever see or manage their own provider's workers; a Tenant Admin
(`labour.configure`) can manage any provider in the tenant, the same
"admin sees everything, a narrower role sees only its own slice" pattern
already used for actions/onboarding.

What this deliberately does not do: let a Labour Provider create or edit
`ShiftAssignment` rows directly. Tempo's own roster optimiser (Phase A/B's
`named_roster` run + Phase E's publish_roster action) remains the single
place shift assignments are decided — a Labour Provider can only view
which shifts their supplied workers have been assigned, the same
read-only relationship every other non-planning role has to the roster.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, ProviderNotFound, ScopeError
from app.models.canonical import LabourProvider, ShiftAssignment, SkillCertification, Worker
from app.schemas.attendance import UpcomingShift
from app.schemas.providers import (
    CertificationCreateRequest,
    CertificationResponse,
    LabourProviderCreateRequest,
    LabourProviderResponse,
    SuppliedWorkerCreateRequest,
    SuppliedWorkerResponse,
)
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["providers"])


def _aware(value: datetime) -> datetime:
    # SQLite round-trips DateTime(timezone=True) columns as naive even
    # though every value here is written in UTC (same fix
    # app/api/v1/onboarding.py and others already apply).
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _get_owned_provider(db: Session, context: RequestContext, provider_id: str) -> LabourProvider:
    provider = db.get(LabourProvider, provider_id)
    if provider is None or provider.tenant_id != context.tenant_id:
        raise ProviderNotFound(f"labour provider '{provider_id}' not found or not visible in caller scope")
    return provider


def _require_provider_access(context: RequestContext, provider: LabourProvider) -> None:
    # Tenant Admin manages every provider in the tenant; a labour_provider
    # caller only ever their own — the same "admin sees everything, a
    # narrower role sees only its own slice" pattern app/api/v1/runs.py's
    # margin_3pl gate and app/api/v1/actions.py's action ownership use.
    if context.has_permission("labour.configure"):
        return
    if not context.has_permission("labour.provider.manage"):
        raise AuthForbidden("caller lacks labour.provider.manage or labour.configure permission")
    if context.provider_id != provider.provider_id:
        raise AuthForbidden("caller's provider_id does not match the requested provider")


@router.post("/providers", response_model=LabourProviderResponse, status_code=201)
def create_provider(
    request: LabourProviderCreateRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> LabourProviderResponse:
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to register a labour provider")
    provider = LabourProvider(tenant_id=context.tenant_id, name=request.name)
    db.add(provider)
    db.flush()
    return LabourProviderResponse(
        provider_id=provider.provider_id, tenant_id=provider.tenant_id, name=provider.name,
        status=provider.status, created_at=_aware(provider.created_at),
    )


@router.get("/providers", response_model=list[LabourProviderResponse])
def list_providers(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> list[LabourProviderResponse]:
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read permission required to view labour providers")
    rows = db.scalars(select(LabourProvider).where(LabourProvider.tenant_id == context.tenant_id)).all()
    return [
        LabourProviderResponse(
            provider_id=r.provider_id, tenant_id=r.tenant_id, name=r.name, status=r.status, created_at=_aware(r.created_at)
        )
        for r in rows
    ]


def _supplied_worker_response(db: Session, worker: Worker) -> SuppliedWorkerResponse:
    certs = db.scalars(select(SkillCertification).where(SkillCertification.worker_id == worker.worker_id)).all()
    shifts = db.scalars(
        select(ShiftAssignment)
        .where(ShiftAssignment.worker_id == worker.worker_id)
        .order_by(ShiftAssignment.start_at.asc())
    ).all()
    return SuppliedWorkerResponse(
        worker_id=worker.worker_id, tenant_id=worker.tenant_id, provider_id=worker.provider_id,
        employment_type=worker.employment_type, home_site=worker.home_site, status=worker.status,
        certifications=[
            CertificationResponse(
                id=c.id, worker_id=c.worker_id, skill_code=c.skill_code, valid_from=_aware(c.valid_from),
                valid_to=_aware(c.valid_to) if c.valid_to else None, level=c.level, evidence_ref=c.evidence_ref,
            )
            for c in certs
        ],
        upcoming_shifts=[
            UpcomingShift(shift_id=s.shift_id, role=s.role, zone=s.zone, start_at=s.start_at, end_at=s.end_at, status=s.status)
            for s in shifts
        ],
    )


@router.post("/providers/{provider_id}/workers", response_model=SuppliedWorkerResponse, status_code=201)
def register_supplied_worker(
    provider_id: str,
    request: SuppliedWorkerCreateRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> SuppliedWorkerResponse:
    provider = _get_owned_provider(db, context, provider_id)
    _require_provider_access(context, provider)
    if context.site_ids and request.home_site not in context.site_ids:
        raise ScopeError(f"home_site '{request.home_site}' exceeds the caller's authorised scope")

    worker = Worker(
        tenant_id=context.tenant_id, employment_type="labour_hire", home_site=request.home_site,
        provider_id=provider.provider_id, source_ref=request.source_ref,
    )
    db.add(worker)
    db.flush()
    return _supplied_worker_response(db, worker)


@router.get("/providers/{provider_id}/workers", response_model=list[SuppliedWorkerResponse])
def list_supplied_workers(
    provider_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> list[SuppliedWorkerResponse]:
    provider = _get_owned_provider(db, context, provider_id)
    _require_provider_access(context, provider)
    workers = db.scalars(
        select(Worker).where(Worker.tenant_id == context.tenant_id).where(Worker.provider_id == provider.provider_id)
    ).all()
    return [_supplied_worker_response(db, w) for w in workers]


@router.post(
    "/providers/{provider_id}/workers/{worker_id}/certifications",
    response_model=CertificationResponse,
    status_code=201,
)
def add_certification(
    provider_id: str,
    worker_id: str,
    request: CertificationCreateRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> CertificationResponse:
    provider = _get_owned_provider(db, context, provider_id)
    _require_provider_access(context, provider)

    worker = db.get(Worker, worker_id)
    if worker is None or worker.tenant_id != context.tenant_id or worker.provider_id != provider.provider_id:
        raise ProviderNotFound(f"worker '{worker_id}' is not supplied by provider '{provider_id}'")

    cert = SkillCertification(
        tenant_id=context.tenant_id, worker_id=worker.worker_id, skill_code=request.skill_code,
        valid_from=request.valid_from, valid_to=request.valid_to, level=request.level, evidence_ref=request.evidence_ref,
    )
    db.add(cert)
    db.flush()
    return CertificationResponse(
        id=cert.id, worker_id=cert.worker_id, skill_code=cert.skill_code, valid_from=_aware(cert.valid_from),
        valid_to=_aware(cert.valid_to) if cert.valid_to else None, level=cert.level, evidence_ref=cert.evidence_ref,
    )
