"""Canonical data model — Integration Spec §6.1.

These tables represent the Maestro canonical layer as seen from Tempo's side.
In production, Maestro connectors own ingestion and write here (or into
Maestro's own store, exposed to Tempo via API/events per DP-03); this Phase 0
scaffold accepts canonical envelopes directly (see app/core/events.py) so the
run pipeline can be exercised end-to-end before a real connector exists.

No row in this file may carry vendor-specific fields (Deputy/UKG names) —
that mapping happens once in a Maestro adapter, never here (DP-03, INT-002).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TenantScope(Base):
    """Tenant/company/site/customer identity registry (§5.1, OD-01)."""

    __tablename__ = "tenant_scope"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    company_id: Mapped[str | None] = mapped_column(String, nullable=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Worker(Base):
    __tablename__ = "worker"

    worker_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    employment_type: Mapped[str] = mapped_column(String)
    home_site: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)


class SkillCertification(Base):
    __tablename__ = "skill_certification"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), index=True)
    skill_code: Mapped[str] = mapped_column(String)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String, nullable=True)


class Availability(Base):
    __tablename__ = "availability"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), index=True)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String)
    preference: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)


class AttendanceSession(Base):
    __tablename__ = "attendance_session"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    breaks_minutes: Mapped[float] = mapped_column(Float, default=0)
    approval: Mapped[str] = mapped_column(String, default="pending")
    pay_code: Mapped[str | None] = mapped_column(String, nullable=True)
    source_system: Mapped[str] = mapped_column(String)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)


class ShiftAssignment(Base):
    __tablename__ = "shift_assignment"

    shift_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), index=True)
    role: Mapped[str] = mapped_column(String)
    zone: Mapped[str] = mapped_column(String)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="proposed")


class DemandBucket(Base):
    __tablename__ = "demand_bucket"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str] = mapped_column(String)
    site_id: Mapped[str] = mapped_column(String)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    volume: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)


class WorkStandard(Base):
    __tablename__ = "work_standard"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str] = mapped_column(String)
    complexity_segment: Mapped[str | None] = mapped_column(String, nullable=True)
    time_per_unit_seconds: Mapped[float] = mapped_column(Float)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivityRoleZoneMap(Base):
    """β_(a,r,z,w) — activity-to-role-zone mapping (AI Labour Optimisation Spec §3.2).

    Not one of the §6.1 canonical entities named in the Integration Spec, but
    required input for the Labour Requirement translation it describes —
    added here as Tempo governed configuration (same authority tier as
    WorkStandard/OptimisationPolicy), not as a Maestro-sourced entity.
    """

    __tablename__ = "activity_role_zone_map"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String)
    activity: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    zone: Mapped[str] = mapped_column(String)
    weight: Mapped[float] = mapped_column(Float, default=1.0)


class LabourCostRule(Base):
    __tablename__ = "labour_cost_rule"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    labour_type: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    rate: Mapped[str] = mapped_column(String)  # decimal-as-string, §8.1 money convention
    overtime_multiplier: Mapped[str | None] = mapped_column(String, nullable=True)
    surcharge: Mapped[str | None] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, default="AUD")


class SellRateContract(Base):
    __tablename__ = "sell_rate_contract"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(String)
    activity: Mapped[str] = mapped_column(String)
    rate: Mapped[str] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String, default="AUD")
    sla_penalty: Mapped[str | None] = mapped_column(String, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OptimisationPolicy(Base):
    __tablename__ = "optimisation_policy"

    policy_version: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    jurisdiction: Mapped[str | None] = mapped_column(String, nullable=True)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    tolerances: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
