"""Labour Provider contracts — Business Spec §8's Labour Provider UX role
("manage supplied workers, certifications, shift assignments") and §5's
"Labour Hire Portal" module. Neither the Integration Spec nor the Business
Spec defines a data model or API contract for this — see
app/models/canonical.py's LabourProvider docstring for how this extends
the existing canonical model rather than duplicating it.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.attendance import UpcomingShift


class LabourProviderCreateRequest(BaseModel):
    name: str


class LabourProviderResponse(BaseModel):
    provider_id: str
    tenant_id: str
    name: str
    status: str
    created_at: datetime


class SuppliedWorkerCreateRequest(BaseModel):
    home_site: str
    source_ref: str | None = None


class CertificationCreateRequest(BaseModel):
    skill_code: str
    valid_from: datetime
    valid_to: datetime | None = None
    level: str | None = None
    evidence_ref: str | None = None


class CertificationResponse(BaseModel):
    id: str
    worker_id: str
    skill_code: str
    valid_from: datetime
    valid_to: datetime | None = None
    level: str | None = None
    evidence_ref: str | None = None


class SuppliedWorkerResponse(BaseModel):
    worker_id: str
    tenant_id: str
    provider_id: str
    employment_type: str
    home_site: str
    status: str
    # Embedded rather than requiring separate calls — a Labour Provider's
    # one real need (§8) is a rollup view of their own supplied workers'
    # certifications and shift assignments, not a general worker directory.
    certifications: list[CertificationResponse] = []
    upcoming_shifts: list[UpcomingShift] = []
