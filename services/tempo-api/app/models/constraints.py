"""Operational constraints (order-driven-planning Stage 3): fill priorities, absenteeism, equipment
pools, headcount limits. See docs/order-driven-planning.md for scope and acceptance scenarios.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class FillPriority(Base):
    """Lower `priority` fills first; equal `priority` values are equal priority (the brief warns
    against inferring an order from a source file that happens to rank two things the same)."""

    __tablename__ = "fill_priority"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    scope: Mapped[str] = mapped_column(String)   # e.g. "activity", "customer", "employment_type"
    value: Mapped[str] = mapped_column(String)   # the scoped value this priority applies to
    priority: Mapped[int] = mapped_column(Integer)


class AbsenteeismRule(Base):
    """An absence-rate assumption for a (site, activity, weekday, shift_code) combination. Resolved
    most-specific-first; two rules with the same specificity matching the same scope are rejected at
    import time rather than silently picking one (brief: "reject ambiguous equal-specificity overlaps")."""

    __tablename__ = "absenteeism_rule"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str | None] = mapped_column(String, nullable=True)
    weekday: Mapped[str | None] = mapped_column(String, nullable=True)
    shift_code: Mapped[str | None] = mapped_column(String, nullable=True)
    absence_pct: Mapped[float] = mapped_column(Float)


class Equipment(Base):
    """A shared pool of equipment units at a site (brief: "Three high-reach trucks allow at most
    three simultaneous one-truck assignments")."""

    __tablename__ = "equipment"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    equipment_id: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)
    quantity_available: Mapped[int] = mapped_column(Integer)


class HeadcountLimit(Base):
    """Concurrent-headcount bounds for one activity (optionally one shift) at a site."""

    __tablename__ = "headcount_limit"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str] = mapped_column(String)
    shift_code: Mapped[str | None] = mapped_column(String, nullable=True)
    min_headcount: Mapped[int] = mapped_column(Integer)
    max_headcount: Mapped[int] = mapped_column(Integer)


class AwardRule(Base):
    """A tenant-configured award/agreement rule: a named identifier plus the actual numbers used in
    costing (ordinary daily hours before overtime, and the overtime multiplier). The award name
    alone is never enough — eligibility/costing only use what this row actually specifies
    (priority 17)."""

    __tablename__ = "award_rule"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    award_code: Mapped[str] = mapped_column(String)
    ordinary_hours_per_day: Mapped[float] = mapped_column(Float)
    overtime_multiplier: Mapped[float] = mapped_column(Float)


class AwardEligibilityRestriction(Base):
    """An EXPLICIT, imported statement that workers under `award_code` may not perform `activity` —
    never inferred from the award's name or any pattern in it (Arch acceptance item 6: "do not infer
    restrictions from an award name or invent restrictions"). Distinct from skill/certification
    eligibility (app.models.canonical.WorkStandard.required_skill / SkillCertification), which gates
    on a worker's qualifications, not their employment agreement. The absence of a row here means no
    restriction — an award with no configured row restricts nothing."""

    __tablename__ = "award_eligibility_restriction"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    award_code: Mapped[str] = mapped_column(String)
    activity: Mapped[str] = mapped_column(String)
