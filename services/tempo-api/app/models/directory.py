"""Site/customer/zone master data, worker PII, source freshness and live exception cases.

Gate 2/3 groundwork. Separate from app/models/canonical.py (what solvers read) so that PII
(`WorkerPerson`) and operational state (`ExceptionCase`, `DataSourceStatus`) have their own
tables and their own permission gates.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Site(Base):
    __tablename__ = "site"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String)  # IANA, e.g. Australia/Melbourne
    # standalone: Tempo is the roster/attendance system of record. overlay: an external WFM/T&A is.
    operating_mode: Mapped[str] = mapped_column(String, default="standalone")
    is_synthetic: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Customer(Base):
    __tablename__ = "customer"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")


class Zone(Base):
    __tablename__ = "zone"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    zone_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkerPerson(Base):
    """Worker personal data. Readable only with `labour.worker_pii`; everything else shows the
    worker's opaque id / masked label."""

    __tablename__ = "worker_person"

    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    display_name: Mapped[str] = mapped_column(String)
    employee_no: Mapped[str | None] = mapped_column(String, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(default=False)


class DataSourceStatus(Base):
    """Where a number came from and how fresh it is. `mode` is never inferred as live:
    only a verified, recent success may be `live`; a seeded/demo source is `simulated`."""

    __tablename__ = "data_source_status"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # native | connector
    mode: Mapped[str] = mapped_column(String)  # live | simulated | stale | error | not_configured
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stale_after_seconds: Mapped[int] = mapped_column(Integer, default=900)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class ExceptionCase(Base):
    """A live operational exception. Lifecycle: detected → triaged → assigned → resolved/dismissed.
    Source occurrence time and Tempo detection time are both kept; repeats dedupe on dedup_key."""

    __tablename__ = "exception_case"
    __table_args__ = (UniqueConstraint("tenant_id", "dedup_key", name="uq_exception_dedup"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # late | no_show | unrostered | missing_punch | early_departure | overtime | cert_expiry | connector_stale
    severity: Mapped[str] = mapped_column(String)  # critical | high | medium | low
    dedup_key: Mapped[str] = mapped_column(String)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    shift_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    state: Mapped[str] = mapped_column(String, default="detected")
    owner_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
