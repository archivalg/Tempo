"""Congestion/off-task loss and staging capacity (order-driven-planning Stage 4). See
docs/order-driven-planning.md for scope and acceptance scenarios.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class ProductivityLoss(Base):
    """An explicit, flat rate reduction (`loss_type == "congestion"`, applied to a rate) or capacity
    reduction (`loss_type == "off_task"`, applied to hours) — never an inferred crowding curve."""

    __tablename__ = "productivity_loss"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    loss_type: Mapped[str] = mapped_column(String)  # congestion | off_task
    activity: Mapped[str | None] = mapped_column(String, nullable=True)
    weekday: Mapped[str | None] = mapped_column(String, nullable=True)
    shift_code: Mapped[str | None] = mapped_column(String, nullable=True)
    percent_loss: Mapped[float | None] = mapped_column(Float, nullable=True)   # congestion
    off_task_hours: Mapped[float | None] = mapped_column(Float, nullable=True)  # off_task


class StagingCapacity(Base):
    """Maximum concurrent occupancy for one zone, in an explicit unit (brief: pallets, not an
    invented universal conversion)."""

    __tablename__ = "staging_capacity"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    zone_id: Mapped[str] = mapped_column(String)
    capacity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String)


class StagingMovement(Base):
    """An arrival, departure, or initial occupancy event for one zone. Quantities must be in the
    same unit as the zone's StagingCapacity — a mismatch means capacity cannot be validated, never a
    guessed conversion."""

    __tablename__ = "staging_movement"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    zone_id: Mapped[str] = mapped_column(String)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    movement_type: Mapped[str] = mapped_column(String)  # initial | arrival | departure
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String)
