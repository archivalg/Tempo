"""Order-driven workload (roadmap M3 extension, order-driven-planning Stage 2).

Process templates map an order (or receipt) to the activities, in sequence, that must happen before
despatch. Orders carry release (order_received) and due (despatch_due) times so workload can be
scheduled against real deadlines instead of only period-bucket forecasts. See docs/order-driven-planning.md.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProcessTemplate(Base):
    """A named sequence of activities an order (or receipt) must pass through before despatch.
    `customer_id` is null for a site's default process; a non-null value overrides it for that customer."""

    __tablename__ = "process_template"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    process_code: Mapped[str] = mapped_column(String)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)


class ProcessStep(Base):
    """One activity in a process template's sequence. `lag_minutes` is the minimum gap after the
    previous step's completion before this step may start (finish-to-start, Stage 2 basic precedence)."""

    __tablename__ = "process_step"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    process_template_id: Mapped[str] = mapped_column(String, ForeignKey("process_template.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    activity: Mapped[str] = mapped_column(String)
    lag_minutes: Mapped[int] = mapped_column(Integer, default=0)
    # Integration increment: a step may consume a shared equipment pool (app.models.constraints.Equipment)
    # and/or deposit its completed quantity into a staging zone (app.models.stage4.StagingCapacity).
    # Both optional and nullable — existing steps without them are unaffected.
    equipment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    zone_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Order(Base):
    """An outbound order (brief Appendix A, v2 Outbound Orders). `units` is the authoritative
    quantity when present; `lines` is only converted to units (via UnitConversion) when `units` is
    absent, so the two are never added together."""

    __tablename__ = "order_"  # "order" is a reserved word in PostgreSQL

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    order_ref: Mapped[str] = mapped_column(String)  # the customer's own order_id, unique per (tenant, site)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    order_received: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    despatch_due: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    units: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String, default="units")
    process_template_id: Mapped[str] = mapped_column(String, ForeignKey("process_template.id"))
    status: Mapped[str] = mapped_column(String, default="open")  # open | completed | cancelled


class OrderTask(Base):
    """A generated link from an order to one of its process steps, for traceability (brief: "Persist
    generated order-task links for traceability"). Timing is computed by the solver at run time, not
    stored here — this table only records which steps apply to which order."""

    __tablename__ = "order_task"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("order_.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    activity: Mapped[str] = mapped_column(String)
    lag_minutes: Mapped[int] = mapped_column(Integer, default=0)


class WorkerActivityRate(Base):
    """A personal rate for one worker performing one activity (brief: individual task rates).
    Distinct from the role-level LabourCostRule, which prices labour, not productivity."""

    __tablename__ = "worker_activity_rate"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), index=True)
    activity: Mapped[str] = mapped_column(String)
    unit: Mapped[str] = mapped_column(String, default="units")
    rate_per_hour: Mapped[float] = mapped_column(Float)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class UnitConversion(Base):
    """A factor to convert one unit to another for an activity (or globally when `activity` is null).
    Never an invented universal ratio — a missing path must be rejected, not guessed."""

    __tablename__ = "unit_conversion"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str | None] = mapped_column(String, nullable=True)
    from_unit: Mapped[str] = mapped_column(String)
    to_unit: Mapped[str] = mapped_column(String)
    factor: Mapped[float] = mapped_column(Float)
