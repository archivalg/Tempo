"""Customer data ingestion (roadmap M1): batches, rows, saved mappings, and the canonical stores the four data classes feed.

Raw evidence is never deleted: batches and rows are kept (the runtime role has no DELETE on them). Derived read-models
(`demand_bucket`) are rebuilt from the evidence, so an undo or correction never loses what was originally received.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ImportBatch(Base):
    """One upload (CSV) or one API submission. States: validated → applied | rejected; applied → undone | superseded."""

    __tablename__ = "import_batch"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("imp"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    data_class: Mapped[str] = mapped_column(String)  # master | forecast | transactions | bulk
    entity: Mapped[str | None] = mapped_column(String, nullable=True)  # master only: workers | work_standards
    channel: Mapped[str] = mapped_column(String)  # csv | xlsx | api — "xlsx" is one sheet of a multi-sheet workbook upload
    source_label: Mapped[str] = mapped_column(String, default="")  # file name or API client name
    content_sha256: Mapped[str] = mapped_column(String, index=True)
    contract_version: Mapped[str] = mapped_column(String, default="1.0")
    state: Mapped[str] = mapped_column(String, default="validated")
    mode: Mapped[str] = mapped_column(String, default="upsert")  # upsert | replace_slice
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    ok_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, default=0)
    warning_rows: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # slice, totals, control total, notes
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    applied_by: Mapped[str | None] = mapped_column(String, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_by: Mapped[str | None] = mapped_column(String, nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportRow(Base):
    __tablename__ = "import_row"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("irw"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    batch_id: Mapped[str] = mapped_column(String, index=True)
    row_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)  # ok | warning | error
    messages: Mapped[list] = mapped_column(JSON, default=list)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    normalised: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # what the row replaced, so undo can restore it
    applied: Mapped[bool] = mapped_column(default=False)


class ImportMapping(Base):
    """A remembered mapping from a customer's column names to Tempo's canonical fields, per data class."""

    __tablename__ = "import_mapping"
    __table_args__ = (UniqueConstraint("tenant_id", "data_class", "entity", "name", name="uq_import_mapping"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("imm"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    data_class: Mapped[str] = mapped_column(String)
    entity: Mapped[str] = mapped_column(String, default="")
    name: Mapped[str] = mapped_column(String, default="default")
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SuppliedForecast(Base):
    """A forecast the customer supplied (as opposed to one Tempo generated). Versioned; the newest active version of a
    bucket wins; provenance is always shown."""

    __tablename__ = "supplied_forecast"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("sfc"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str] = mapped_column(String)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bucket_minutes: Mapped[int] = mapped_column(Integer)
    units: Mapped[float] = mapped_column(Float)
    lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    version: Mapped[str] = mapped_column(String)
    batch_id: Mapped[str] = mapped_column(String, index=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String, default="active")  # active | removed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WorkloadEvent(Base):
    """An individual operational workload event (units processed). Latest revision wins; replays are no-ops."""

    __tablename__ = "workload_event"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "event_id", name="uq_workload_event"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("wev"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String)
    event_id: Mapped[str] = mapped_column(String)
    site_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str] = mapped_column(String)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String, default="units")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String, default="active")  # active | cancelled | undone
    payload_hash: Mapped[str] = mapped_column(String)
    batch_id: Mapped[str] = mapped_column(String, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActualsPolicy(Base):
    """Which kind of actuals is authoritative for a site + activity, so the same work is never counted twice."""

    __tablename__ = "actuals_policy"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    activity: Mapped[str] = mapped_column(String, primary_key=True)
    authority: Mapped[str] = mapped_column(String)  # transactions | bulk
    set_by: Mapped[str] = mapped_column(String)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reason: Mapped[str] = mapped_column(String, default="")


class SiteForecastPreference(Base):
    __tablename__ = "site_forecast_preference"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, default="generated")  # generated | supplied
    set_by: Mapped[str] = mapped_column(String)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
