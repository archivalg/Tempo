"""Recurring weekly availability pattern and personal start/finish windows (integration increment,
priority 2). Distinct from `app.models.canonical.Availability`, which remains the dated-exception/
leave mechanism that overrides this pattern for a specific date. See docs/order-driven-planning.md.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class WeeklyAvailabilityPattern(Base):
    """One weekday's default availability for a worker. `earliest_start`/`latest_finish` are
    "HH:MM" local wall-clock; `latest_finish <= earliest_start` means the personal window crosses
    midnight (same convention as ShiftTemplate). Null times with `available=True` means available
    all day; `available=False` means unavailable the whole day regardless of times."""

    __tablename__ = "weekly_availability_pattern"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), index=True)
    weekday: Mapped[str] = mapped_column(String)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    earliest_start: Mapped[str | None] = mapped_column(String, nullable=True)
    latest_finish: Mapped[str | None] = mapped_column(String, nullable=True)
