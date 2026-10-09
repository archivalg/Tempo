"""Versioned shift/calendar master data (roadmap M3 extension, order-driven-planning Stage 1).

Replaces the implicit assumption that a site's operating hours and shift definitions live only in
`OptimisationPolicy.constraints` JSON (app/solvers/shifts.py) with explicit, imported, auditable rows.
See docs/order-driven-planning.md.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class OperatingCalendarDay(Base):
    """One site's operating interval for one weekday. `is_24h` and `is_closed` are explicit so an
    equal open/close time can never be silently read as either state (brief: "equal start/end cannot
    silently mean both closed and 24 hours")."""

    __tablename__ = "operating_calendar_day"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    weekday: Mapped[str] = mapped_column(String)  # monday..sunday
    is_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    open_time: Mapped[str | None] = mapped_column(String, nullable=True)   # "HH:MM", local wall-clock
    close_time: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ShiftTemplate(Base):
    """A named, site-scoped shift definition (brief: Shift Templates). Supersedes
    `OptimisationPolicy.constraints["shift_calendar"]` as the source of truth once a tenant has
    uploaded templates; that JSON remains the fallback for tenants with none (app/solvers/shifts.py)."""

    __tablename__ = "shift_template"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    shift_code: Mapped[str] = mapped_column(String)
    start_time: Mapped[str] = mapped_column(String)  # "HH:MM" local wall-clock
    end_time: Mapped[str] = mapped_column(String)    # <= start_time means the shift crosses midnight
    weekdays: Mapped[list] = mapped_column(JSON, default=list)  # subset of WEEKDAYS
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class ShiftBreak(Base):
    """A scheduled break within a shift template. `starts_after_minutes` is measured from the
    shift's own start, so it is unambiguous across midnight-crossing shifts."""

    __tablename__ = "shift_break"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    shift_template_id: Mapped[str] = mapped_column(String, ForeignKey("shift_template.id"), index=True)
    starts_after_minutes: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
